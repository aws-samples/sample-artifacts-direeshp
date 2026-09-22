import json
import logging
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Resilient client configuration: adaptive retries absorb API throttling so the
# function scales safely across many roles/regions without manual sleeps.
BOTO_CONFIG = Config(
    retries={"max_attempts": 10, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=60,
)

# Error codes that indicate eventual-consistency conditions worth retrying
# (IAM role/SLR propagation, MGN service still initializing).
RETRYABLE_ERROR_CODES = frozenset({
    "UninitializedAccountException",
    "AccessDeniedException",  # transient right after role/policy propagation
    "ThrottlingException",
    "TooManyRequestsException",
    "ConflictException",
})


def _error_code(exc):
    """Extract the AWS error code from a botocore ClientError."""
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code", "")
    return ""


def retry_with_backoff(func, *, description, max_attempts=5, base_delay=2, max_delay=20):
    """
    Retry an AWS call with exponential backoff on eventual-consistency errors.
    Replaces fixed time.sleep() calls so propagation waits are bounded by the
    actual condition clearing, not an arbitrary duration.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except ClientError as exc:
            last_exc = exc
            code = _error_code(exc)
            if code not in RETRYABLE_ERROR_CODES or attempt == max_attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            logger.warning(
                "%s: retryable error %s (attempt %d/%d), backing off %ds",
                description, code, attempt, max_attempts, delay,
            )
            time.sleep(delay)
    if last_exc:
        raise last_exc


def get_mgn_roles_config(account_id):
    """Define all MGN roles with required policies."""
    return [
        {
            'name': 'AWSApplicationMigrationReplicationServerRole',
            'trust_policy': {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            },
            'managed_policies': ['arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationReplicationServerPolicy'],
            'needs_instance_profile': True
        },
        {
            'name': 'AWSApplicationMigrationConversionServerRole',
            'trust_policy': {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            },
            'managed_policies': ['arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationConversionServerPolicy'],
            'needs_instance_profile': True
        },
        {
            'name': 'AWSApplicationMigrationMGHRole',
            'trust_policy': {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "mgn.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            },
            'managed_policies': ['arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationMGHAccess'],
            'needs_instance_profile': False
        },
        {
            'name': 'AWSApplicationMigrationLaunchInstanceWithDrsRole',
            'trust_policy': {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            },
            'managed_policies': [
                'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
                'arn:aws:iam::aws:policy/service-role/AWSElasticDisasterRecoveryEc2InstancePolicy'
            ],
            'needs_instance_profile': True
        },
        {
            'name': 'AWSApplicationMigrationLaunchInstanceWithSsmRole',
            'trust_policy': {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            },
            'managed_policies': ['arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'],
            'needs_instance_profile': True
        },
        {
            'name': 'AWSApplicationMigrationAgentRole',
            'trust_policy': {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "mgn.amazonaws.com"},
                    "Action": ["sts:AssumeRole", "sts:SetSourceIdentity"],
                    "Condition": {
                        "StringLike": {
                            "sts:SourceIdentity": "s-*",
                            "aws:SourceAccount": account_id
                        }
                    }
                }]
            },
            'managed_policies': ['arn:aws:iam::aws:policy/service-role/AWSApplicationMigrationAgentPolicy_v2'],
            'needs_instance_profile': False
        }
    ]


# =============================================================================
# STEP 1: Check and verify IAM roles and SLR
# =============================================================================

def check_service_linked_role(iam_client):
    """Check if MGN service-linked role exists."""
    try:
        iam_client.get_role(RoleName='AWSServiceRoleForApplicationMigrationService')
        logger.info("SLR exists: AWSServiceRoleForApplicationMigrationService")
        return {'exists': True, 'status': 'Already exists'}
    except iam_client.exceptions.NoSuchEntityException:
        logger.info("SLR does not exist")
        return {'exists': False, 'status': 'Not found'}


def create_service_linked_role(iam_client):
    """Create MGN service-linked role."""
    try:
        iam_client.create_service_linked_role(AWSServiceName='mgn.amazonaws.com')
        logger.info("Created SLR: AWSServiceRoleForApplicationMigrationService")
        return {'status': 'Created'}
    except iam_client.exceptions.InvalidInputException:
        return {'status': 'Already exists'}
    except Exception as e:
        return {'status': f'Error: {str(e)}'}


def check_role_exists(iam_client, role_name):
    """Check if a role exists."""
    try:
        iam_client.get_role(RoleName=role_name)
        return True
    except iam_client.exceptions.NoSuchEntityException:
        return False


def check_role_policies(iam_client, role_name, required_policies):
    """Check if role has all required policies attached. Returns missing policies."""
    try:
        attached = iam_client.list_attached_role_policies(RoleName=role_name)
        attached_arns = {p['PolicyArn'] for p in attached['AttachedPolicies']}
        missing = [p for p in required_policies if p not in attached_arns]
        return {
            'attached': list(attached_arns),
            'required': required_policies,
            'missing': missing,
            'compliant': len(missing) == 0
        }
    except Exception as e:
        return {'error': str(e), 'compliant': False}


def check_instance_profile(iam_client, role_name):
    """Check if instance profile exists and has role attached."""
    try:
        response = iam_client.get_instance_profile(InstanceProfileName=role_name)
        roles = [r['RoleName'] for r in response['InstanceProfile']['Roles']]
        return {
            'exists': True,
            'role_attached': role_name in roles
        }
    except iam_client.exceptions.NoSuchEntityException:
        return {'exists': False, 'role_attached': False}


def scan_all_mgn_roles(iam_client, account_id):
    """
    STEP 1: Scan all existing IAM roles and check their policies.
    Returns detailed status of each role.
    """
    logger.info("Step 1: Scanning existing IAM roles...")
    roles_config = get_mgn_roles_config(account_id)
    scan_results = {'roles': [], 'all_roles_ready': True, 'all_policies_correct': True}
    
    for role_config in roles_config:
        role_name = role_config['name']
        role_status = {
            'name': role_name,
            'exists': False,
            'policies_correct': False,
            'instance_profile_ready': not role_config['needs_instance_profile']
        }
        
        # Check if role exists
        if check_role_exists(iam_client, role_name):
            role_status['exists'] = True
            
            # Check policies
            policy_check = check_role_policies(iam_client, role_name, role_config['managed_policies'])
            role_status['policy_check'] = policy_check
            role_status['policies_correct'] = policy_check.get('compliant', False)
            
            # Check instance profile if needed
            if role_config['needs_instance_profile']:
                profile_check = check_instance_profile(iam_client, role_name)
                role_status['instance_profile'] = profile_check
                role_status['instance_profile_ready'] = profile_check['exists'] and profile_check['role_attached']
        else:
            scan_results['all_roles_ready'] = False
        
        if not role_status['policies_correct']:
            scan_results['all_policies_correct'] = False
        
        scan_results['roles'].append(role_status)
    
    # Check SLR
    slr_check = check_service_linked_role(iam_client)
    scan_results['service_linked_role'] = slr_check
    if not slr_check['exists']:
        scan_results['all_roles_ready'] = False
    
    logger.info(f"Scan complete: all_roles_ready={scan_results['all_roles_ready']}, all_policies_correct={scan_results['all_policies_correct']}")
    return scan_results


# =============================================================================
# STEP 2 & 3: Fix missing policies and create missing roles
# =============================================================================

def fix_role_policies(iam_client, role_name, missing_policies):
    """Attach missing policies to a role."""
    actions = []
    for policy_arn in missing_policies:
        try:
            iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
            actions.append(f"Attached: {policy_arn.split('/')[-1]}")
            logger.info(f"Attached {policy_arn} to {role_name}")
        except Exception as e:
            actions.append(f"Failed to attach {policy_arn.split('/')[-1]}: {str(e)}")
    return actions


def create_role_with_policies(iam_client, role_config):
    """Create a role and attach all required policies."""
    role_name = role_config['name']
    actions = []
    
    try:
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(role_config['trust_policy']),
            Description=f"MGN service role: {role_name}"
        )
        actions.append('Created role')
        logger.info(f"Created role: {role_name}")
        
        for policy_arn in role_config['managed_policies']:
            iam_client.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
            actions.append(f"Attached: {policy_arn.split('/')[-1]}")
        
        return {'status': 'Created', 'actions': actions}
    except Exception as e:
        return {'status': f'Failed: {str(e)}', 'actions': actions}


def ensure_instance_profile(iam_client, role_name):
    """Ensure instance profile exists and has role attached."""
    actions = []
    
    # Create instance profile if needed
    try:
        iam_client.create_instance_profile(InstanceProfileName=role_name)
        actions.append('Created instance profile')
    except iam_client.exceptions.EntityAlreadyExistsException:
        pass
    
    # Add role to instance profile
    try:
        iam_client.add_role_to_instance_profile(InstanceProfileName=role_name, RoleName=role_name)
        actions.append('Added role to instance profile')
    except iam_client.exceptions.LimitExceededException:
        pass  # Role already attached
    except Exception as e:
        actions.append(f'Instance profile error: {str(e)}')
    
    return actions


def ensure_all_roles_ready(iam_client, account_id, scan_results):
    """
    STEP 2 & 3: Fix policies on existing roles and create missing roles.
    """
    logger.info("Step 2 & 3: Ensuring all roles are ready...")
    roles_config = get_mgn_roles_config(account_id)
    fix_results = {'actions': []}
    
    # Create SLR if missing
    if not scan_results['service_linked_role']['exists']:
        slr_result = create_service_linked_role(iam_client)
        fix_results['service_linked_role'] = slr_result
    
    # Process each role
    for role_config in roles_config:
        role_name = role_config['name']
        role_scan = next((r for r in scan_results['roles'] if r['name'] == role_name), None)
        
        if role_scan and role_scan['exists']:
            # Role exists - check and fix policies
            if not role_scan['policies_correct']:
                missing = role_scan.get('policy_check', {}).get('missing', [])
                if missing:
                    actions = fix_role_policies(iam_client, role_name, missing)
                    fix_results['actions'].append({
                        'role': role_name,
                        'action': 'Fixed policies',
                        'details': actions
                    })
            
            # Ensure instance profile
            if role_config['needs_instance_profile'] and not role_scan['instance_profile_ready']:
                actions = ensure_instance_profile(iam_client, role_name)
                if actions:
                    fix_results['actions'].append({
                        'role': role_name,
                        'action': 'Fixed instance profile',
                        'details': actions
                    })
        else:
            # Role doesn't exist - create it
            create_result = create_role_with_policies(iam_client, role_config)
            fix_results['actions'].append({
                'role': role_name,
                'action': 'Created role',
                'details': create_result
            })
            
            # Create instance profile if needed
            if role_config['needs_instance_profile']:
                actions = ensure_instance_profile(iam_client, role_name)
                if actions:
                    fix_results['actions'].append({
                        'role': role_name,
                        'action': 'Created instance profile',
                        'details': actions
                    })
    
    logger.info(f"Role setup complete: {len(fix_results['actions'])} actions taken")
    return fix_results


# =============================================================================
# STEP 4: Initialize MGN
# =============================================================================

def initialize_mgn_service(mgn_client):
    """
    STEP 4: Initialize MGN service.
    """
    logger.info("Step 4: Initializing MGN service...")
    try:
        # Retry absorbs the IAM/SLR propagation window instead of a blind sleep.
        retry_with_backoff(
            mgn_client.initialize_service,
            description="mgn.initialize_service",
        )
        logger.info("MGN service initialized successfully")
        return {'status': 'Initialized', 'message': 'MGN service initialized successfully'}
    except ClientError as e:
        error_msg = str(e)
        if 'already initialized' in error_msg.lower():
            logger.info("MGN service already initialized")
            return {'status': 'Already initialized', 'message': 'Service was already initialized'}
        logger.error(f"MGN initialization failed: {error_msg}")
        return {'status': 'Failed', 'error': error_msg}


# =============================================================================
# STEP 5: Update Replication Configuration Template
# =============================================================================

def get_existing_replication_template(mgn_client):
    """Get existing replication configuration template if any."""
    try:
        response = mgn_client.describe_replication_configuration_templates(maxResults=1)
        if response.get('items'):
            return response['items'][0]
        return None
    except Exception as e:
        logger.error(f"Error getting replication template: {str(e)}")
        return None


def create_or_update_replication_template(mgn_client, ec2_client, event):
    """
    STEP 5: Create or update replication configuration template.
    """
    logger.info("Step 5: Configuring replication template...")
    
    # Get VPC resources
    staging_subnet_id = event.get('stagingAreaSubnetId')
    security_group_ids = event.get('replicationServersSecurityGroupsIDs', [])
    
    # Auto-discover if not provided
    if not staging_subnet_id:
        try:
            vpcs = ec2_client.describe_vpcs(Filters=[{'Name': 'is-default', 'Values': ['true']}])
            if vpcs['Vpcs']:
                vpc_id = vpcs['Vpcs'][0]['VpcId']
                subnets = ec2_client.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
                if subnets['Subnets']:
                    staging_subnet_id = subnets['Subnets'][0]['SubnetId']
                    logger.info(f"Auto-discovered subnet: {staging_subnet_id}")
        except Exception as e:
            logger.error(f"VPC discovery failed: {str(e)}")
    
    if not security_group_ids and staging_subnet_id:
        try:
            subnet_info = ec2_client.describe_subnets(SubnetIds=[staging_subnet_id])
            vpc_id = subnet_info['Subnets'][0]['VpcId']
            sgs = ec2_client.describe_security_groups(Filters=[
                {'Name': 'vpc-id', 'Values': [vpc_id]},
                {'Name': 'group-name', 'Values': ['default']}
            ])
            if sgs['SecurityGroups']:
                security_group_ids = [sgs['SecurityGroups'][0]['GroupId']]
                logger.info(f"Auto-discovered security group: {security_group_ids[0]}")
        except Exception as e:
            logger.error(f"Security group discovery failed: {str(e)}")
    
    if not staging_subnet_id:
        return {'status': 'Skipped', 'reason': 'No subnet available'}
    
    # Check for existing template
    existing = get_existing_replication_template(mgn_client)
    
    replication_params = {
        'stagingAreaSubnetId': staging_subnet_id,
        'replicationServerInstanceType': event.get('replicationServerInstanceType', 't3.small'),
        'replicationServersSecurityGroupsIDs': security_group_ids,
        'associateDefaultSecurityGroup': event.get('associateDefaultSecurityGroup', True),
        'bandwidthThrottling': int(event.get('bandwidthThrottling', 0)),
        # Secure defaults: no public IP and private data-plane routing unless
        # the caller explicitly opts in. Prevents replication traffic from
        # traversing the public internet by default.
        'createPublicIP': event.get('createPublicIP', False),
        'dataPlaneRouting': event.get('dataPlaneRouting', 'PRIVATE_IP'),
        'defaultLargeStagingDiskType': event.get('defaultLargeStagingDiskType', 'GP3'),
        'ebsEncryption': event.get('ebsEncryption', 'DEFAULT'),
        'useDedicatedReplicationServer': event.get('useDedicatedReplicationServer', False),
        'stagingAreaTags': event.get('stagingAreaTags', {}),
    }
    
    if existing:
        # Update existing template
        try:
            template_id = existing['replicationConfigurationTemplateID']
            replication_params['replicationConfigurationTemplateID'] = template_id
            retry_with_backoff(
                lambda: mgn_client.update_replication_configuration_template(**replication_params),
                description="mgn.update_replication_configuration_template",
            )
            logger.info(f"Updated replication template: {template_id}")
            return {
                'status': 'Updated',
                'templateId': template_id,
                'stagingSubnet': staging_subnet_id
            }
        except ClientError as e:
            return {'status': 'Update failed', 'error': str(e)}
    else:
        # Create new template
        try:
            response = retry_with_backoff(
                lambda: mgn_client.create_replication_configuration_template(**replication_params),
                description="mgn.create_replication_configuration_template",
            )
            template_id = response['replicationConfigurationTemplateID']
            logger.info(f"Created replication template: {template_id}")
            return {
                'status': 'Created',
                'templateId': template_id,
                'stagingSubnet': staging_subnet_id
            }
        except ClientError as e:
            return {'status': 'Create failed', 'error': str(e)}


# =============================================================================
# STEP 6: Launch Configuration Template with Post-Launch Actions
# =============================================================================

def get_existing_launch_template(mgn_client):
    """Get existing launch configuration template if any."""
    try:
        response = mgn_client.describe_launch_configuration_templates(maxResults=1)
        if response.get('items'):
            return response['items'][0]
        return None
    except Exception as e:
        logger.error(f"Error getting launch template: {str(e)}")
        return None


def create_or_update_launch_template(mgn_client, event):
    """
    STEP 6: Create or update launch configuration template with post-launch actions.
    """
    logger.info("Step 6: Configuring launch template...")
    
    existing = get_existing_launch_template(mgn_client)
    
    # Base launch parameters
    launch_params = {
        'launchDisposition': event.get('launchDisposition', 'STARTED'),
        'targetInstanceTypeRightSizingMethod': event.get('targetInstanceTypeRightSizingMethod', 'BASIC'),
        'copyPrivateIp': event.get('copyPrivateIp', False),
        'copyTags': event.get('copyTags', False),
        'bootMode': event.get('bootMode', 'USE_SOURCE'),
        'licensing': {'osByol': event.get('osByol', False)},
        'enableMapAutoTagging': event.get('enableMapAutoTagging', False),
        'smallVolumeConf': event.get('smallVolumeConf', {
            'volumeType': 'gp3',
            'iops': 3000,
            'throughput': 125
        }),
        'largeVolumeConf': event.get('largeVolumeConf', {
            'volumeType': 'gp3',
            'iops': 3000,
            'throughput': 125
        }),
        # Post-launch actions - activated
        'postLaunchActions': {
            'deployment': event.get('postLaunchDeployment', 'TEST_AND_CUTOVER'),
            'ssmDocuments': []
        }
    }
    
    # Add MAP tagging MPE ID if provided
    if event.get('mapAutoTaggingMpeId'):
        launch_params['mapAutoTaggingMpeId'] = event['mapAutoTaggingMpeId']
    
    if existing:
        # Update existing template
        try:
            template_id = existing['launchConfigurationTemplateID']
            launch_params['launchConfigurationTemplateID'] = template_id
            response = retry_with_backoff(
                lambda: mgn_client.update_launch_configuration_template(**launch_params),
                description="mgn.update_launch_configuration_template",
            )
            logger.info(f"Updated launch template: {template_id}")
            
            return {
                'status': 'Updated',
                'templateId': template_id,
                'ec2LaunchTemplateId': existing.get('ec2LaunchTemplateID', 'N/A'),
                'postLaunchActionsEnabled': True
            }
        except ClientError as e:
            return {'status': 'Update failed', 'error': str(e)}
    else:
        # Create new template
        try:
            response = retry_with_backoff(
                lambda: mgn_client.create_launch_configuration_template(**launch_params),
                description="mgn.create_launch_configuration_template",
            )
            template_id = response['launchConfigurationTemplateID']
            ec2_template_id = response.get('ec2LaunchTemplateID', 'pending')
            logger.info(f"Created launch template: {template_id}, EC2: {ec2_template_id}")
            
            return {
                'status': 'Created',
                'templateId': template_id,
                'ec2LaunchTemplateId': ec2_template_id,
                'postLaunchActionsEnabled': True
            }
        except Exception as e:
            return {'status': 'Create failed', 'error': str(e)}


# =============================================================================
# MAIN HANDLER
# =============================================================================

def lambda_handler(event, context):
    """
    MGN Initialization Lambda Handler.
    
    Flow:
    1. Scan existing IAM roles and SLR
    2. Check all policies are correct
    3. Create missing roles/fix policies
    4. Initialize MGN service
    5. Update replication configuration template
    6. Update launch configuration template with post-launch actions
    """
    iam = boto3.client('iam', config=BOTO_CONFIG)
    mgn = boto3.client('mgn', config=BOTO_CONFIG)
    sts = boto3.client('sts', config=BOTO_CONFIG)
    ec2 = boto3.client('ec2', config=BOTO_CONFIG)

    results = {}
    failures = []

    try:
        account_id = sts.get_caller_identity()['Account']
        region = boto3.session.Session().region_name

        logger.info(f"Starting MGN initialization for account {account_id} in {region}")
        results['account'] = account_id
        results['region'] = region

        # STEP 1: Scan existing IAM roles
        scan_results = scan_all_mgn_roles(iam, account_id)
        results['step1_role_scan'] = {
            'all_roles_ready': scan_results['all_roles_ready'],
            'all_policies_correct': scan_results['all_policies_correct'],
            'slr_exists': scan_results['service_linked_role']['exists']
        }

        # STEP 2 & 3: Fix policies and create missing roles. IAM propagation is
        # absorbed by retry_with_backoff on the subsequent MGN calls, so no
        # fixed sleep is needed here.
        if not scan_results['all_roles_ready'] or not scan_results['all_policies_correct']:
            fix_results = ensure_all_roles_ready(iam, account_id, scan_results)
            results['step2_3_role_fixes'] = fix_results
        else:
            results['step2_3_role_fixes'] = {'status': 'No fixes needed'}

        # STEP 4: Initialize MGN
        init_result = initialize_mgn_service(mgn)
        results['step4_mgn_init'] = init_result
        if init_result['status'] == 'Failed':
            failures.append(f"MGN initialization failed: {init_result.get('error')}")

        # STEP 5: Replication Configuration Template
        replication_result = create_or_update_replication_template(mgn, ec2, event)
        results['step5_replication_template'] = replication_result
        if 'failed' in str(replication_result.get('status', '')).lower():
            failures.append(f"Replication template: {replication_result.get('error')}")

        # STEP 6: Launch Configuration Template with Post-Launch Actions
        launch_result = create_or_update_launch_template(mgn, event)
        results['step6_launch_template'] = launch_result
        if 'failed' in str(launch_result.get('status', '')).lower():
            failures.append(f"Launch template: {launch_result.get('error')}")

        # Fail loudly so Terraform surfaces the error instead of a silent 200.
        if failures:
            raise RuntimeError("MGN initialization incomplete: " + "; ".join(failures))

        logger.info("MGN initialization completed successfully")
        return {
            'statusCode': 200,
            'body': json.dumps(results, default=str)
        }

    except Exception as e:
        # Log full context, then re-raise so the invocation returns a
        # FunctionError and `terraform apply` fails visibly.
        logger.error(f"MGN initialization error: {str(e)}")
        logger.error("Partial results: %s", json.dumps(results, default=str))
        raise
