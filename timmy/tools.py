#!/usr/bin/env python2
# -*- coding: utf-8 -*-

#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
tools module
"""

import os
import logging
import sys
import threading
import multiprocessing
import subprocess


slowpipe = '''
import sys
import time
while 1:
    a = sys.stdin.read(int(1250*%s))
    if a:
        sys.stdout.write(a)
        time.sleep(0.01)
    else:
        break
'''


def interrupt_wrapper(f):
    def wrapper(*args, **kwargs):
        try:
            f(*args, **kwargs)
        except KeyboardInterrupt:
            logging.warning('Interrupted, exiting.')

    return wrapper


class SemaphoreProcess(multiprocessing.Process):
    def __init__(self, semaphore, target, args):
        multiprocessing.Process.__init__(self)
        self.semaphore = semaphore
        self.target = target
        self.args = args
    def run(self):
        try:
           self.target(**self.args)
        finally:
            try:
                logging.info('finished task: %s' % self.args['cmd'])
            except:
                pass
            self.semaphore.release()


def get_dir_structure(rootdir):
    """
    Creates a nested dictionary that represents the folder structure of rootdir
    """
    dir = {}
    try:
        rootdir = rootdir.rstrip(os.sep)
        start = rootdir.rfind(os.sep) + 1
        for path, dirs, files in os.walk(rootdir):
            folders = path[start:].split(os.sep)
            subdir = dict.fromkeys(files)
            parent = reduce(dict.get, folders[:-1], dir)
            parent[folders[-1]] = subdir
    except:
        logging.error('failed to create list of the directory: %s' % rootdir)
        sys.exit(1)
    return dir


def mdir(directory):
    if not os.path.exists(directory):
        logging.debug('creating directory %s' % directory)
        try:
            os.makedirs(directory)
        except:
            logging.error("Can't create a directory: %s" % directory)
            sys.exit(3)


def launch_cmd(command, timeout):
    def _timeout_terminate(pid):
        try:
            os.kill(pid, 15)
            logging.error("launch_cmd: pid %d killed by timeout" % pid)
        except:
            pass

    logging.info('launch_cmd: command %s' % command)
    p = subprocess.Popen(command,
                         shell=True,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    timeout_killer = None
    try:
        timeout_killer = threading.Timer(timeout, _timeout_terminate, [p.pid])
        timeout_killer.start()
        outs, errs = p.communicate()
    except:
        if p and not p.poll():
            p.kill()
        outs, errs = p.communicate()
        logging.error("command: %s err: %s, returned: %s" %
                      (command, errs, p.returncode))
    finally:
        if timeout_killer:
            timeout_killer.cancel()
    logging.debug("ssh return: err:%s\nouts:%s\ncode:%s" %
                  (errs, outs, p.returncode))
    logging.info("ssh return: err:%s\ncode:%s" %
                 (errs, p.returncode))
    return outs, errs, p.returncode


def ssh_node(ip, command, ssh_opts=[], env_vars=[], timeout=15, filename=None,
             inputfile=None, outputfile=None, prefix='nice -n 19 ionice -c 3'):
    if type(ssh_opts) is list:
        ssh_opts = ' '.join(ssh_opts)
    if type(env_vars) is list:
        env_vars = ' '.join(env_vars)
    if (ip in ['localhost', '127.0.0.1']) or ip.startswith('127.'):
        logging.info("skip ssh")
        bstr = "%s timeout '%s' bash -c " % (
               env_vars, timeout)
    else:
        logging.info("exec ssh")
        # base cmd str
        bstr = "timeout '%s' ssh -t -T %s '%s' '%s' " % (
               timeout, ssh_opts, ip, env_vars)
    if filename is None:
        cmd = bstr + '"' + prefix + ' ' + command + '"'
    else:
        cmd = bstr + " '%s bash -s' < '%s'" % (prefix, filename)
    if inputfile is not None:
        cmd = bstr + '"' + prefix + " " + command + '" < ' + inputfile
        logging.info("ssh_node: inputfile selected, cmd: %s" % cmd)
    if outputfile is not None:
        cmd += ' > "' + outputfile + '"'
    cmd = ("trap 'kill $pid' 15; " + 
          "trap 'kill $pid' 2; " + cmd + '&:; pid=$!; wait $!')
    outs, errs, code = launch_cmd(cmd, timeout)
    return outs, errs, code

def killall_children(timeout):
    cmd = 'ps -o pid --ppid %d --noheaders' % os.getpid()
    out, errs, code = launch_cmd(cmd, timeout)
    if code != 0:
        logging.error("can't get pids")
    else:
        ppids = set(out.split())
        pkill = []
        haschildren = True
        while haschildren:
            parentspids = []
            haschildren = False
            for proc in ppids:
                cmd = 'ps -o pid --ppid %s --noheaders' % proc
                out, errs, code = launch_cmd(cmd, timeout)
                if code != 0:
                    pkill.append(proc)
                else:
                    parentspids += out.split()
                    haschildren = True
            ppids = parentspids
        logging.info(pkill)
        for p in pkill:
            try:
                os.kill(int(p), 2)
            except:
                logging.warning('could not kill %s' % p)

def get_files_rsync(ip, data, ssh_opts, dpath, timeout=15):
    if type(ssh_opts) is list:
        ssh_opts = ' '.join(ssh_opts)
    if (ip in ['localhost', '127.0.0.1']) or ip.startswith('127.'):
        logging.info("skip ssh rsync")
        cmd = ("timeout '%s' rsync -avzr --files-from=- / '%s'"
               " --progress --partial --delete-before" %
               (timeout, dpath))
    else:
        cmd = ("timeout '%s' rsync -avzr -e 'ssh %s"
               " -oCompression=no' --files-from=- '%s':/ '%s'"
               " --progress --partial --delete-before"
               ) % (timeout, ssh_opts, ip, dpath)
    logging.debug("command:%s\ndata:\n%s" % (cmd, data))
    if data == '':
        return cmd, '', 127
    p = subprocess.Popen(cmd,
                         shell=True,
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    try:
        outs, errs = p.communicate(input=data)
    except:
        p.kill()
        outs, errs = p.communicate()
        logging.error("ip: %s, command: %s err: %s, returned: %s" %
                      (ip, cmd, errs, p.returncode))

    logging.debug("ip: %s, ssh return: err:%s\nouts:%s\ncode:%s" %
                  (ip, errs, outs, p.returncode))
    logging.info("ip: %s, ssh return: err:%s\ncode:%s" %
                 (ip, errs, p.returncode))
    return outs, errs, p.returncode


def free_space(destdir, timeout):
    cmd = ("df %s --block-size K 2> /dev/null"
           " | tail -n 1 | awk '{print $2}' | sed 's/K//g'") % (destdir)
    outs, errs, code = launch_cmd(cmd, timeout)
    return outs, errs, code


if __name__ == '__main__':
    exit(0)
