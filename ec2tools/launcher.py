#!/usr/bin/env python3

import os
import sys
import json
import argparse
import inspect
import datetime
import pdb
import subprocess
from shutil import which
import boto3
from botocore.exceptions import ClientError
from veryprettytable import VeryPrettyTable
from pyaws.ec2 import default_region
from pyaws.utils import stdout_message, export_json_object, userchoice_mapping, range_bind
from pyaws.session import authenticated, boto3_session, parse_profiles
from pyaws import Colors
from ec2tools.statics import local_config
from ec2tools import current_ami, logd, __version__
from ec2tools.environment import profile_securitygroups, profile_keypairs, profile_subnets

try:
    from pyaws.core.oscodes_unix import exit_codes
except Exception:
    from pyaws.core.oscodes_win import exit_codes    # non-specific os-safe codes

# globals
module = os.path.basename(__file__)
logger = logd.getLogger(__version__)
act = Colors.ORANGE
yl = Colors.YELLOW
bd = Colors.BOLD + Colors.WHITE
frame = Colors.BOLD + Colors.BRIGHTGREEN
rst = Colors.RESET
PACKAGE = 'runmachine'
PKG_ACCENT = Colors.ORANGE
PARAM_ACCENT = Colors.WHITE
AMI = Colors.DARKCYAN

FILE_PATH = local_config['CONFIG']['CONFIG_DIR']

image, subnet, securitygroup, keypair = None, None, None, None
launch_prereqs = (image, subnet, securitygroup, keypair)


def help_menu():
    """ Displays command line parameter options """
    synopsis_cmd = (
        Colors.RESET + PKG_ACCENT + Colors.BOLD + PACKAGE + rst +
        PARAM_ACCENT + '  --image ' + Colors.RESET + '{' + AMI + 'OS_TYPE' + rst + '}' +
        PARAM_ACCENT + '  --region' + Colors.RESET + ' <value>' +
        PARAM_ACCENT + '  [ --profile' + Colors.RESET + ' <value> ]'
        )

    menu = """
                        """ + bd + PACKAGE + rst + """ help contents
                        ------------------------

  """ + bd + """DESCRIPTION""" + rst + """

        Launch one or more EC2 virtual server instances in a specified AWS
        region. Automatically finds the latest Amazon Machine Image of the
        operation system type specified (Windows & Linux).

  """ + bd + """SYNOPSYS""" + rst + """

          """ + synopsis_cmd + """

                       -i, --image    <value>
                       -r, --region   <value>
                      [-p, --profile  <value>  ]
                      [-q, --quantity  <value> ]
                      [-s, --instance-size <value> ]
                      [-d, --debug     ]
                      [-h, --help      ]

  """ + bd + """OPTIONS
      -i, --image""" + rst + """  (string):  Amazon  Machine  Image Operating System type
          Returns the latest AMI of the type specified from the list below

                  """ + bd + """Amazon EC2 Machine Image types""" + rst + """:

              - """ + AMI + """amazonlinux1""" + rst + """  :  Amazon Linux v1 (2018)
              - """ + AMI + """amazonlinux2""" + rst + """  :  Amazon Linux v2 (2017.12+)
              - """ + AMI + """centos6""" + rst + """       :  CentOS 6 (RHEL 6+)
              - """ + AMI + """centos7""" + rst + """       :  CentOS 7 (RHEL 7+)
              - """ + AMI + """redhat""" + rst + """        :  Latest Redhat Enterprise Linux
              - """ + AMI + """redhat7.4""" + rst + """     :  Redhat Enterprise Linux 7.4
              - """ + AMI + """redhat7.5""" + rst + """     :  Redhat Enterprise Linux 7.5
              - """ + AMI + """ubuntu14.04""" + rst + """   :  Ubuntu Linux 14.04
              - """ + AMI + """ubuntu16.04""" + rst + """   :  Ubuntu Linux 16.04
              - """ + AMI + """ubuntu18.04""" + rst + """   :  Ubuntu Linux 18.04
              - """ + AMI + """windows2012""" + rst + """   :  Microsoft Windows Server 2012 R2
              - """ + AMI + """windows2016""" + rst + """   :  Microsoft Windows Server 2016


      """ + bd + """-s""" + rst + """, """ + bd + """--instance-size""" + rst + """ (string):  Defines the EC2 instance size type at
          launch time. Default: t3.micro unless otherwise specified.

      """ + bd + """-p""" + rst + """, """ + bd + """--profile""" + rst + """ (string): IAM username or role corresponding to an STS
          (Secure Token Service) profile from local awscli configuration.

      """ + bd + """-q""" + rst + """, """ + bd + """--quantity""" + rst + """:  Quantity of identical EC2 servers created at launch

      """ + bd + """-r""" + rst + """, """ + bd + """--region""" + rst + """ (string): AWS region code designating a specific launch
          region.

      """ + bd + """-d""" + rst + """, """ + bd + """--debug""" + rst + """: Debug mode, verbose output.

      """ + bd + """-V""" + rst + """, """ + bd + """--version""" + rst + """: Display program version information

      """ + bd + """-h""" + rst + """, """ + bd + """--help""" + rst + """: Print this menu
    """
    print(menu)
    return True


def choose_resource(choices, selector='letters', default='a'):
    """

    Summary.

        validate user choice of options

    Args:
        :choices (dict): lookup table by key, for value selected
            from options displayed via stdout

    Returns:
        user selected resource identifier
    """
    def safe_choice(sel_index, user_choice):
        if sel_index == 'letters':
            return user_choice
        elif isinstance(user_choice, int):
            return user_choice
        elif isinstance(user_choice, str):
            try:
                return int(user_choice)
            except TypeError:
                return userchoice_mapping(user_choice)

    validate = True

    try:
        while validate:
            choice = input(
                '\n\tEnter a letter to select [%s]: '.expandtabs(8) %
                (choices[userchoice_mapping(default)] if selector == 'letters' else choices[int(default)])
            ) or default

            # prevent entering of letters for choice if numbered selector index
            choice = safe_choice(selector, choice)

            index_range = [x for x in choices]

            if range_test(0, max(index_range), userchoice_mapping(choice) if selector == 'letters' else int(choice)):
                resourceid = choices[userchoice_mapping(choice)] if selector == 'letters' else choices[int(choice)]
                validate = False
            else:
                stdout_message(
                    'You must enter a %s between %s and %s' %
                    (
                        'letter' if selector == 'letters' else 'number',
                        userchoice_mapping(index_range[0]) if selector == 'letters' else index_range[0],
                        userchoice_mapping(index_range[-1]) if selector == 'letters' else index_range[-1]
                    )
                )
    except KeyError:
        resourceid = None
        choice = [k for k, v in choices.items() if v is None]
    except TypeError as e:
        logger.exception(f'Typed input caused an exception. Error {e}')
        sys.exit(1)
    stdout_message('You selected choice {}, {}'.format(choice, resourceid))
    return resourceid


def display_table(table, tabspaces=4):
    """Print Table Object offset from left by tabspaces"""
    indent = ('\t').expandtabs(tabspaces)
    table_str = table.get_string()
    for e in table_str.split('\n'):
        print(indent + frame + e)
    sys.stdout.write(Colors.RESET)
    return True


def find_instanceprofile_roles(profile):
    """
    Summary.

        returns instance profile roles in an AWS account

    Returns:
        iam role information, TYPE:  json
        Format:
            {
                'RoleName': 'SR-S3Ops',
                'Arn': 'arn:aws:iam::716400000000:role/SR-S3Ops',
                'CreateDate':
            }
    """
    client = boto3_session(service='iam', profile=profile)
    r = client.list_roles()['Roles']
    return [
            {
                'RoleName': x['RoleName'],
                'Arn': x['Arn'],
                'CreateDate': x['CreateDate'].strftime('%Y-%m-%dT%H:%M:%S')
            } for x in r
        ]


def ip_lookup(profile, region, debug):
    """
    Summary.

        Instance Profile role user selection

    Returns:
        iam instance profile role ARN (str) or None
    """
    now = datetime.datetime.utcnow()

    # setup table
    x = VeryPrettyTable(border=True, header=True, padding_width=2)
    field_max_width = 60

    x.field_names = [
        bd + '#' + frame,
        bd + 'RoleName' + frame,
        bd + 'RoleArn' + frame,
        bd + 'CreateDate' + frame
    ]

    # cell alignment
    x.align[bd + '#' + frame] = 'c'
    x.align[bd + 'RoleName' + frame] = 'l'
    x.align[bd + 'RoleArn' + frame] = 'l'
    x.align[bd + 'CreateDate' + frame] = 'c'

    roles = find_instanceprofile_roles(parse_profiles(profile))

    # populate table
    lookup = {}
    for index, iprofile in enumerate(roles):

            lookup[index] = iprofile['Arn']

            x.add_row(
                [
                    rst + str(index) + '.' + frame,
                    rst + iprofile['RoleName'] + frame,
                    rst + iprofile['Arn'][:field_max_width] + frame,
                    rst + iprofile['CreateDate'] + frame
                ]
            )

    # add default choice (None)
    lookup[index + 1] = None
    x.add_row(
        [
            rst + str(index + 1) + '.' + frame,
            rst + 'Default' + frame,
            None,
            rst + now.strftime('%Y-%m-%dT%H:%M:%S') + frame
        ]
    )
    # Table showing selections
    print(f'\n\tInstance Profile Roles (global directory)\n'.expandtabs(26))
    display_table(x, tabspaces=4)
    return choose_resource(lookup, selector='numbers', default=(index + 1))


def is_tty():
    """
    Summary:
        Determines if output is displayed to the screen or redirected
    Returns:
        True if tty terminal | False is redirected, TYPE: bool
    """
    return sys.stdout.isatty()


def get_account_identifier(profile, returnAlias=True):
    """ Returns account alias """
    client = boto3_session(service='iam', profile=profile)
    alias = client.list_account_aliases()['AccountAliases'][0]
    if alias and returnAlias:
        return alias
    client = boto3_session(service='sts', profile=profile)
    return client.get_caller_identity()['Account']


def get_regions():
    client = boto3_session('ec2')
    return [x['RegionName'] for x in client.describe_regions()['Regions'] if 'cn' not in x['RegionName']]


def keypair_lookup(profile, region, debug):
    """
    Summary.

        Returns name of keypair user selection in given region

    Args:
        :profile (str): profile_name from local awscli configuration
        :region (str): AWS region code

    Returns:
        keypair name chosen by user

    """
    # setup table
    x = VeryPrettyTable(border=True, header=True, padding_width=2)
    field_max_width = 30

    x.field_names = [
        bd + '#' + frame,
        bd + 'Keypair' + frame
    ]


    # cell alignment
    x.align[bd + '#' + frame] = 'c'
    x.align[bd + 'Keypair' + frame] = 'l'

    keypairs = profile_keypairs(parse_profiles(profile), region)[region]

    # populate table
    lookup = {}
    for index, keypair in enumerate(keypairs):

            lookup[index] = keypair

            x.add_row(
                [
                    rst + userchoice_mapping(index) + '.' + frame,
                    rst + keypair + frame
                ]
            )

    # Table showing selections
    print(f'\n\tKeypairs in region {bd + region + rst}\n'.expandtabs(26))
    display_table(x, tabspaces=16)
    return choose_resource(lookup)


def options(parser):
    """
    Summary:
        parse cli parameter options
    Returns:
        TYPE: argparse object, parser argument set
    """
    parser.add_argument("-p", "--profile", nargs='?', default="default",
                              required=False, help="type (default: %(default)s)")
    parser.add_argument("-d", "--debug", dest='debug', action='store_true', default=False, required=False)
    parser.add_argument("-i", "--image", dest='imagetype', type=str, choices=current_ami.VALID_AMI_TYPES, required=False)
    parser.add_argument("-q", "--quantity", dest='quantity', nargs='?', default=1, required=False)
    parser.add_argument("-r", "--region", dest='regioncode', nargs='?', default=None, required=False)
    parser.add_argument("-s", "--instance-size", dest='instance_size', nargs='?', default='t3.micro', required=False)
    parser.add_argument("-t", "--tags", dest='tags', action='store_true', default=False, required=False)
    parser.add_argument("-V", "--version", dest='version', action='store_true', required=False)
    parser.add_argument("-h", "--help", dest='help', action='store_true', required=False)
    return parser.parse_args()


def get_contents(content):
    with open(FILE_PATH + '/' + content) as f1:
        f2 = f1.read()
        return json.loads(f2)
    return None


def get_imageid(profile, image, region):
    if which('machineimage'):
        cmd = 'machineimage --profile {} --image {} --region {}'.format(profile, image, region)
        response = json.loads(subprocess.getoutput(cmd))
    else:
        stdout_message('machineimage executable could not be located. Exit', prefix='WARN')
        sys.exit(1)
    return response[region]


def get_subnet(account_file, region):
    """
    Summary.

        Returns subnet user selection in given region

    Args:
        :profile (str): profile_name from local awscli configuration
        :region (str): AWS region code

    Returns:
        subnet id chosen by user

    """
    # setup table
    x = VeryPrettyTable(border=True, header=True, padding_width=2)
    field_max_width = 30

    x.field_names = [
        bd + '#' + frame,
        bd + 'SubnetId' + frame,
        bd + 'AZ' + frame,
        bd + 'CIDR' + frame,
        bd + 'Ip Assign' + frame,
        bd + 'State' + frame,
        bd + 'VpcId' + frame
    ]

    subnets = get_contents(account_file)[region]['Subnets']

    # populate table
    lookup = {}
    for index, row in enumerate(subnets):
        for k,v in row.items():

            lookup[index] = k

            x.add_row(
                [
                    rst + userchoice_mapping(index) + '.' + frame,
                    rst + k + frame,
                    rst + v['AvailabilityZone'] + frame,
                    rst + v['CidrBlock'] + frame,
                    rst + v['IpAddresses'] + frame,
                    rst + v['State'] + frame,
                    rst + v['VpcId'] + frame
                ]
            )

    # Table showing selections
    print(f'\n\tSubnets in region {bd + region + rst}\n'.expandtabs(30))
    display_table(x)
    return choose_resource(lookup)


def nametag(imagetype, date):

    default = imagetype + '-' + date

    choice = input(
        'Enter Name tag you want displayed in the console [{}]: '.format(default)
    )
    if not choice:
        return default
    elif choice is 'None':
        return None
    return choice


def parameters_approved(alias, region, subid, imageid, sg, kp, ip, size, ct):
    print('\tEC2 Instance Launch Summary:\n')
    print('\t' + bd + 'AWS Account' + rst + ': \t\t{}'.format(alias))
    print('\t' + bd + 'Instance Count' + rst + ': \t{}'.format(ct))
    print('\t' + bd + 'Size Type' + rst + ': \t\t{}'.format(size))
    print('\t' + bd + 'Region' + rst + ': \t\t{}'.format(region))
    print('\t' + bd + 'ImageId' + rst + ': \t\t{}'.format(imageid))
    print('\t' + bd + 'Subnet Id' + rst + ': \t\t{}'.format(subid))
    print('\t' + bd + 'Security GroupId' + rst + ': \t{}'.format(sg))
    print('\t' + bd + 'Keypair Name' + rst + ': \t\t{}'.format(kp))
    print('\t' + bd + 'Instance Profile' + rst + ': \t{}'.format(ip))

    choice = input('\n\tCreate EC2 instance? [yes]: ')

    if choice in ('yes', 'y', True, 'True', 'true', ''):
        return True
    return False


def range_test(min, max, value):
    """
    Summary.

        Tests value to determine if in range (min, max)

    Args:
        :min (int):  integer representing minimum acceptable value
        :max (int):  integer representing maximum acceptable value
        :value (int): value tested

    Returns:
        Success | Failure, TYPE: bool

    """
    if isinstance(int(value), int):
        if value in range(min, max + 1):
            return True
    return False


def profile_securitygroups(profile, region):
    """ Profiles securitygroups in an aws account """
    sgs = []

    try:
        client = boto3_session('ec2', region=region, profile=profile)
        r = client.describe_security_groups()['SecurityGroups']
        sgs.append([
                {
                    x['GroupId']: {
                        'Description': x['Description'],
                        'GroupName': x['GroupName'],
                        'VpcId': x['VpcId']
                    }
                } for x in r
            ])
    except ClientError as e:
        logger.warning(
            '{}: Unable to retrieve securitygroups for region {}'.format(inspect.stack()[0][3], rgn)
            )
    return sgs[0]


def read(fname):
    basedir = os.path.dirname(sys.argv[0])
    return open(os.path.join(basedir, fname)).read()


def sg_lookup(profile, region, debug):
    """
    Summary.

        Returns securitygroup user selection in given region

    Args:
        :profile (str): profile_name from local awscli configuration
        :region (str): AWS region code

    Returns:
        securitygroup ID chosen by user

    """
    padding = 2
    field_max_width = 50
    max_gn, max_desc = 10, 10         # starting value to find max length of a table field (chars)

    x = VeryPrettyTable(border=True, header=True, padding_width=padding)

    sgs = profile_securitygroups(profile, region)
    for index, row in enumerate(sgs):
        for k,v in row.items():
            if len(v['GroupName']) > max_gn:
                max_gn = len(v['GroupName'])
            if len(v['Description']) > max_desc:
                max_desc = len(v['GroupName'])

    if debug:
        print('max_gn = {}'.format(max_gn))
        print('max_desc = {}'.format(max_desc))

    # GroupName header
    tabspaces_gn = int(max_gn / 4 ) - int(len('GroupName') / 2) + padding
    tab_gn = '\t'.expandtabs(tabspaces_gn)

    # Description header
    tabspaces_desc = int(max_desc / 4) - int(len('Description') / 2) + padding
    tab_desc = '\t'.expandtabs(tabspaces_desc)

    x.field_names = [
        bd + ' # ' + frame,
        bd + 'GroupId' + frame,
        tab_gn + bd + 'GroupName' + frame,
        bd + 'VpcId' + frame,
        tab_desc + bd + 'Description' + frame
    ]

    # cell alignment
    x.align = 'c'
    x.align[tab_gn + bd + 'GroupName' + frame] = 'l'
    x.align[tab_desc + bd + 'Description' + frame] = 'l'

    # populate table
    lookup = {}
    for index, row in enumerate(sgs):
        for k,v in row.items():

            lookup[index] = k

            x.add_row(
                [
                    rst + userchoice_mapping(index) + '.' + frame,
                    rst + k + frame,
                    rst + v['GroupName'][:field_max_width] + frame,
                    rst + v['VpcId'] + frame,
                    rst + v['Description'][:field_max_width] + frame
                ]
            )

    # Table showing selections
    print(f'\n\tSecurity Groups in region {bd + region + rst}\n'.expandtabs(30))
    display_table(x)
    return choose_resource(lookup)


def parse_userdata(ostype):
    """
    Summary.

        Parses userdata appropriate for operation system deployed

    Returns:
        userdata (str)
    """
    if ostype.split('.')[0] in PYTHON3_OS_IMAGES:
        from userdata import content
    return (str(content))


def persist_launchconfig(alias, pf, region, imageid, imagetype, subid, sgroup, kp, ip_arn, size):
    """Writes launch config to disk for reuse"""
    fname = alias + '_' + region + '.json'
    content = {
        'account': alias,
        'region': region,
        'profile': pf,
        'imageId': imageid,
        'subnetId': subid,
        'SecurityGroupIds': [ sgroup ],
        'KeypairNames': [ kp ],
        'InstanceProfileArn': 'None' if ip_arn is None else ip_arn,
        'InstanceType': size
    }
    try:
        if not os.path.exists(FILE_PATH + '/' + 'launchconfigs'):
            os.makedirs(FILE_PATH + '/' + 'launchconfigs')

        with open(FILE_PATH + '/launchconfigs/' + fname, 'w') as f1:
            f1.write(json.dumps(content, indent=4))
        stdout_message('Created terminate script: {}'.format(os.getcwd() + '/' + fname))
    except OSError as e:
        logger.exception(
            '%s: Problem creating terminate script (%s) on local fs' %
            (inspect.stack()[0][3], fname))
        return False
    return True


def run_ec2_instance(pf, region, imageid, imagetype, subid, sgroup, kp, ip_arn, size, count, debug):
    """
    Summary.

        Creates a new EC2 instance with properties given by supplied parameters

    Args:
        :imageid (str): Amazon Machine Image Id
        :subid (str): AWS subnet id (subnet-abcxyz)
        :sgroup (str): Security group id
        :kp (str): keypair name matching pre-existing keypair in the targeted AWS account
        :debug (bool): debug flag to enable verbose logging

    Returns:
        InstanceId(s), TYPE: list
    """
    now = datetime.datetime.utcnow()
    # ec2 client instantiation for launch
    client = boto3_session('ec2', region=region, profile=pf)

    # prep default userdata if none specified
    if imagetype.split('.')[0] in ('ubuntu18'):
        from ec2tools import python3_userdata as userdata
        userdata_str = read(os.path.abspath(userdata.__file__))
    else:
        #from ec2tools import python2-userdata as userdata
        from ec2tools import userdata
        userdata_str = userdata.content


    # name tag content
    name_tag = nametag(imagetype, now.strftime('%Y-%m-%d'))

    tags = [
        {
            'Key': 'Name',
            'Value': name_tag
        },
        {
            'Key': 'os',
            'Value': imagetype
        },
        {
            'Key': 'CreateDateTime',
            'Value': now.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    ]

    try:
        if ip_arn is None:
            response = client.run_instances(
                ImageId=imageid,
                InstanceType=size,
                KeyName=kp,
                MaxCount=count,
                MinCount=1,
                SecurityGroupIds=[sgroup],
                SubnetId=subid,
                UserData=userdata_str,
                DryRun=debug,
                InstanceInitiatedShutdownBehavior='stop',
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': tags
                    }
                ]
            )
        else:
            response = client.run_instances(
                ImageId=imageid,
                InstanceType=size,
                KeyName=kp,
                MaxCount=count,
                MinCount=1,
                SecurityGroupIds=[sgroup],
                SubnetId=subid,
                UserData=userdata_str,
                DryRun=debug,
                IamInstanceProfile={
                    'Name': ip_arn.split('/')[-1]
                },
                InstanceInitiatedShutdownBehavior='stop',
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': tags
                    }
                ]
            )
    except ClientError as e:
        if e.response['Error']['Code'] == 'UnauthorizedOperation':
            stdout_message(
                message="IAM user has inadequate permissions to launch EC2 instance(s) (Code: %s)" %
                        e.response['Error']['Code'],
                prefix='WARN'
            )
            sys.exit(exit_codes['EX_NOPERM']['Code'])
        else:
            logger.critical(
                "%s: Unknown problem launching EC2 Instance(s) (Code: %s Message: %s)" %
                (inspect.stack()[0][3], e.response['Error']['Code'], e.response['Error']['Message']))
            return []
    return [x['InstanceId'] for x in response['Instances']]


def terminate_script(id_list, profile):
    """Creates termination script on local fs"""
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    fname = 'terminate-script-' + now + '.sh'
    content = """
        #!/usr/bin/env bash

        pkg=$(basename $0)

        if [[ $(which aws) ]]; then
            aws ec2 terminate-instances \
            --profile """ + profile +  """  \
            --instance-ids """  + [x for x in id_list][0] +  """
        fi

        # delete caller
        rm ./$pkg
        exit 0
    """
    try:
        with open(os.getcwd() + '/' + fname, 'w') as f1:
            f1.write(content)
        stdout_message('Created terminate script: {}'.format(os.getcwd() + '/' + fname))
    except OSError as e:
        logger.exception(
            '%s: Problem creating terminate script (%s) on local fs' %
            (inspect.stack()[0][3], fname))
        return False
    return True


def init_cli():
    """
    Initializes commandline script
    """
    #pdb.set_trace()
    parser = argparse.ArgumentParser(add_help=False)

    try:
        args = options(parser)
    except Exception as e:
        stdout_message(str(e), 'ERROR')
        sys.exit(exit_codes['EX_OK']['Code'])

    if len(sys.argv) == 1:
        help_menu()
        sys.exit(exit_codes['EX_OK']['Code'])

    elif args.help:
        help_menu()
        sys.exit(exit_codes['EX_OK']['Code'])

    elif args.imagetype is None:
        stdout_message(f'You must enter an os image type (--image)', prefix='WARN')
        stdout_message(f'Valid image types are:')
        for t in current_ami.VALID_AMI_TYPES:
            print('\t\t' + t)
        sys.exit(exit_codes['EX_OK']['Code'])

    elif args.profile:

        regioncode = args.regioncode or default_region(args.profile)

        if authenticated(profile=parse_profiles(args.profile)):

            account_alias = get_account_identifier(parse_profiles(args.profile or 'default'))
            DEFAULT_OUTPUTFILE = account_alias + '.profile'
            subnet = get_subnet(DEFAULT_OUTPUTFILE, regioncode)
            image = get_imageid(parse_profiles(args.profile), args.imagetype, regioncode)
            securitygroup = sg_lookup(parse_profiles(args.profile), regioncode, args.debug)
            keypair = keypair_lookup(parse_profiles(args.profile), regioncode, args.debug)
            role_arn = ip_lookup(parse_profiles(args.profile), regioncode, args.debug)
            qty = args.quantity

            if any(x for x in launch_prereqs) is None:
                stdout_message(
                    message='One or more launch prerequisities missing. Abort',
                    prefix='WARN'
                )

            elif parameters_approved(account_alias, regioncode, subnet, image, securitygroup,
                                                keypair, role_arn, args.instance_size, qty):
                persist_launchconfig(
                        alias=account_alias,
                        pf=parse_profiles(args.profile),
                        region=regioncode,
                        imageid=image,
                        imagetype=args.imagetype,
                        subid=subnet,
                        sgroup=securitygroup,
                        kp=keypair,
                        ip_arn=role_arn,
                        size=args.instance_size,
                    )

                r = run_ec2_instance(
                        pf=parse_profiles(args.profile),
                        region=regioncode,
                        imageid=image,
                        imagetype=args.imagetype,
                        subid=subnet,
                        sgroup=securitygroup,
                        kp=keypair,
                        ip_arn=role_arn,
                        size=args.instance_size,
                        count=args.quantity,
                        debug=args.debug
                    )
                print('\tLaunching instances: \n\t\t{}'.format(x + ', ' for x in r if len(r) > 0))
                return terminate_script(r, parse_profiles(args.profile))

            else:
                logger.info('User aborted EC2 launch')
    return False


if __name__ == '__main__':
    sys.exit(init_cli())
