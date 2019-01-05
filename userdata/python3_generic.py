#!/usr/bin/env python3

import os
import inspect
import platform
import subprocess
from pwd import getpwnam as userinfo
import logging
import logging.handlers
import distro


url_bashrc = 'https://s3.us-east-2.amazonaws.com/awscloud.center/files/bashrc'
url_aliases = 'https://s3.us-east-2.amazonaws.com/awscloud.center/files/bash_aliases'
url_colors = 'https://s3.us-east-2.amazonaws.com/awscloud.center/files/colors.sh'

def download(url_list):
    """
    Retrieve remote file object
    """
    def exists(object):
        if os.path.exists(os.getcwd() + '/' + filename):
            return True
        else:
            msg = 'File object %s failed to download to %s. Exit' % (filename, os.getcwd())
            logger.warning(msg)
            stdout_message('%s: %s' % (inspect.stack()[0][3], msg))
            return False
    try:
        for url in url_list:

            if which('wget'):
                cmd = 'wget ' + url
                subprocess.getoutput(cmd)
                logger.info("downloading " + url)

            elif which('curl'):
                cmd = 'curl -o ' + os.path.basename(url) + ' ' + url
                subprocess.getoutput(cmd)
                logger.info("downloading " + url)

            else:
                logger.info('Failed to download {} no url binary found'.format(os.path.basename(url)))
                return False
    except Exception as e:
        logger.info(
            'Error downloading file: {}, URL: {}, Error: {}'.format(os.path.basename(url), url, e)
        )
        return False
    return True


def getLogger(*args, **kwargs):
    """
    Summary:
        custom format logger

    Args:
        mode (str):  The Logger module supprts the following log modes:
            - log to system logger (syslog)

    Returns:
        logger object | TYPE: logging
    """
    syslog_facility = 'local7'
    syslog_format = '[INFO] - %(pathname)s - %(name)s - [%(levelname)s]: %(message)s'

    # all formats
    asctime_format = "%Y-%m-%d %H:%M:%S"

    # objects
    logger = logging.getLogger(*args, **kwargs)
    logger.propagate = False

    try:
        if not logger.handlers:
            # branch on output format, default to stream
            sys_handler = logging.handlers.SysLogHandler(address='/dev/log', facility=syslog_facility)
            sys_formatter = logging.Formatter(syslog_format)
            sys_handler.setFormatter(sys_formatter)
            logger.addHandler(sys_handler)
            logger.setLevel(logging.DEBUG)
    except OSError as e:
        raise e
    return logger


def os_type():
    """
    Summary.

        Identify operation system environment

    Return:
        os type (str) Linux | Windows
        If Linux, return Linux distribution
    """
    if platform.system() == 'Windows':
        return 'Windows'
    elif platform.system() == 'Linux':
        return platform.linux_distribution()[0]


def local_profile_setup(distro):
    """Configures local user profile"""
    home_dir = None

    if os.path.exists('/home/ec2-user'):
        userid = userinfo('ec2-user').pw_uid
        groupid = userinfo('ec2-user').pw_gid
        home_dir = '/home/ec2-user'

    elif os.path.exists('/home/ubuntu'):
        userid = userinfo('ubuntu').pw_uid
        groupid = userinfo('ubuntu').pw_gid
        home_dir = '/home/ubuntu'

    elif os.path.exists('/home/centos'):
        userid = userinfo('centos').pw_uid
        groupid = userinfo('centos').pw_gid
        home_dir = '/home/centos'

    else:
        return False

    try:

        os.chdir(home_dir)

        filename = '.bashrc'
        if download([url_bashrc]):
            logger.info('Download of {} successful to {}'.format(filename, home_dir))
            os.rename(os.path.split(url_bashrc)[1], filename)
            os.chown(filename, groupid, userid)
            os.chmod(filename, 0o700)

        filename = '.bash_aliases'
        if download([url_aliases]):
            logger.info('Download of {} successful to {}'.format(filename, home_dir))
            os.rename(os.path.split(url_aliases)[1], '.bash_aliases')
            os.chown(filename, groupid, userid)
            os.chmod(filename, 0o700)

        filename = 'colors.sh'
        destination = home_dir + '/.config/bash'
        if download([url_colors]):
            logger.info('Download of {} successful to {}'.format(filename, home_dir))

            if not os.path.exists(destination):
                os.makedirs(destination)
            os.rename(filename, destination + '/' + filename)
            os.chown(filename, groupid, userid)
            os.chmod(filename, 0o700)

    except OSError as e:
        logger.exception(
            'Unknown problem downloading or installing local user profile artifacts')
        return False
    return True


def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file


# --- main -----------------------------------------------------------------------------------------


# setup logging facility
logger = getLogger('1.0')

if platform.system() == 'Linux':
    logger.info('Operating System type identified: Linux, {}'.format(os_type()))
    local_profile_setup(os_type())
else:
    logger.info('Operating System type identified: {}'.format(os_type()))
