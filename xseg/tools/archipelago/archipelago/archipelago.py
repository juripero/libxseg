#!/usr/bin/env python

# Copyright 2012 GRNET S.A. All rights reserved.
#
# Redistribution and use in source and binary forms, with or
# without modification, are permitted provided that the following
# conditions are met:
#
#   1. Redistributions of source code must retain the above
#      copyright notice, this list of conditions and the following
#      disclaimer.
#   2. Redistributions in binary form must reproduce the above
#      copyright notice, this list of conditions and the following
#      disclaimer in the documentation and/or other materials
#      provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY GRNET S.A. ``AS IS'' AND ANY EXPRESS
# OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL GRNET S.A OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and
# documentation are those of the authors and should not be
# interpreted as representing official policies, either expressed
# or implied, of GRNET S.A.
#


from xseg.xseg_api import *
from xseg.xprotocol import *
from ctypes import CFUNCTYPE, cast, c_void_p, addressof, string_at, memmove, \
    create_string_buffer, pointer, sizeof, POINTER, c_char_p, c_char, byref, \
    c_uint32, c_uint64
cb_null_ptrtype = CFUNCTYPE(None, uint32_t)

import os, sys, subprocess, argparse, time, psutil, signal, errno
from subprocess import call, check_call, Popen, PIPE
from collections import namedtuple
from struct import unpack
from binascii import hexlify

#archipelago peer roles. Order matters!
roles = ['blockerb', 'blockerm', 'mapperd', 'vlmcd']
Peer = namedtuple('Peer', ['executable', 'opts', 'role'])

peers = dict()
xsegbd_args = []
modules = ['xseg', 'segdev', 'xseg_posix', 'xseg_pthread', 'xseg_segdev']
xsegbd = 'xsegbd'

LOG_SUFFIX='.log'
PID_SUFFIX='.pid'
DEFAULTS='/etc/default/archipelago'
VLMC_LOCK_FILE='vlmc.lock'
ARCHIP_PREFIX='archip_'
CEPH_CONF_FILE='/etc/ceph/ceph.conf'

#system defaults
PIDFILE_PATH="/var/run/archipelago"
LOGS_PATH="/var/log/archipelago"
LOCK_PATH="/var/lock"
DEVICE_PREFIX="/dev/xsegbd"
XSEGBD_SYSFS="/sys/bus/xsegbd/"

CHARDEV_NAME="/dev/segdev"
CHARDEV_MAJOR=60
CHARDEV_MINOR=0

REQS=512

FILE_BLOCKER='mt-pfiled'
RADOS_BLOCKER='mt-sosd'
MAPPER='mt-mapperd'
VLMC='st-vlmcd'
BLOCKER=''

available_storage = {'files': FILE_BLOCKER, 'rados': RADOS_BLOCKER}


XSEGBD_START=0
XSEGBD_END=499
VPORT_START=500
VPORT_END=999
BPORT=1000
MPORT=1001
MBPORT=1002
VTOOL=1003
#RESERVED 1023

#default config
SPEC="segdev:xsegbd:1024:5120:12"

NR_OPS_BLOCKERB=""
NR_OPS_BLOCKERM=""
NR_OPS_VLMC=""
NR_OPS_MAPPER=""

VERBOSITY_BLOCKERB=""
VERBOSITY_BLOCKERM=""
VERBOSITY_MAPPER=""
VERBOSITY_VLMC=""


#mt-pfiled specific options
FILED_IMAGES=""
FILED_MAPS=""
PITHOS=""
PITHOSMAPS=""

#mt-sosd specific options
RADOS_POOL_MAPS=""
RADOS_POOL_BLOCKS=""

FIRST_COLUMN_WIDTH = 23
SECOND_COLUMN_WIDTH = 23

def green(s):
    return '\x1b[32m' + str(s) + '\x1b[0m'

def red(s):
    return '\x1b[31m' + str(s) + '\x1b[0m'

def yellow(s):
    return '\x1b[33m' + str(s) + '\x1b[0m'

def pretty_print(cid, status):
    sys.stdout.write(cid.ljust(FIRST_COLUMN_WIDTH))
    sys.stdout.write(status.ljust(SECOND_COLUMN_WIDTH))
    sys.stdout.write('\n')
    return

class Error(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

def check_conf():
    def isExec(file_path):
        return os.path.isfile(file_path) and os.access(file_path, os.X_OK)

    def validExec(program):
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if isExec(exe_file):
                return True
        return False


    def validPort(port, limit, name):
        try:
            if int(port) >= limit:
                print red(str(port) + " >= " + limit)
                return False
        except:
            print red("Invalid port "+name+" : " + str(port))
            return False

        return True


    if not LOGS_PATH:
        print red("LOGS_PATH is not set")
        return False
    if not PIDFILE_PATH:
        print red("PIDFILE_PATH is not set")
        return False

    try:
        if not os.path.isdir(str(LOGS_PATH)):
            print red("LOGS_PATH "+str(LOGS_PATH)+" does not exist")
            return False
    except:
        print red("LOGS_PATH doesn't exist or is not a directory")
        return False

    try:
        os.makedirs(str(PIDFILE_PATH))
    except OSError as e:
        if e.errno == errno.EEXIST:
            if os.path.isdir(str(PIDFILE_PATH)):
                pass
            else:
                print red(str(PIDFILE_PATH) + " is not a directory")
                return False
        else:
            print red("Cannot create " + str(PIDFILE_PATH))
            return False
    except:
        print red("PIDFILE_PATH is not set")
        return False

    splitted_spec = str(SPEC).split(':')
    if len(splitted_spec) < 5:
        print red("Invalid spec")
        return False

    xseg_type=splitted_spec[0]
    xseg_name=splitted_spec[1]
    xseg_ports=int(splitted_spec[2])
    xseg_heapsize=int(splitted_spec[3])
    xseg_align=int(splitted_spec[4])

    if xseg_type != "segdev":
        print red("Segment type not segdev")
        return False
    if xseg_name != "xsegbd":
        print red("Segment name not equal xsegbd")
        return False
    if xseg_align != 12:
        print red("Wrong alignemt")
        return False

    for v in [VERBOSITY_BLOCKERB, VERBOSITY_BLOCKERM, VERBOSITY_MAPPER,
                    VERBOSITY_VLMC]:
         if v is None:
             print red("Verbosity missing")
         try:
             if (int(v) > 3 or int(v) < 0):
                 print red("Invalid verbosity " + str(v))
                 return False
         except:
             print red("Invalid verbosity " + str(v))
             return False

    for n in [NR_OPS_BLOCKERB, NR_OPS_BLOCKERM, NR_OPS_VLMC, NR_OPS_MAPPER]:
         if n is None:
             print red("Nr ops missing")
         try:
             if (int(n) <= 0):
                 print red("Invalid nr_ops " + str(n))
                 return False
         except:
             print red("Invalid nr_ops " + str(n))
             return False

    if not validPort(VTOOL, xseg_ports, "VTOOL"):
        return False
    if not validPort(MPORT, xseg_ports, "MPORT"):
        return False
    if not validPort(BPORT, xseg_ports, "BPORT"):
        return False
    if not validPort(MBPORT, xseg_ports, "MBPORT"):
        return False
    if not validPort(VPORT_START, xseg_ports, "VPORT_START"):
        return False
    if not validPort(VPORT_END, xseg_ports, "VPORT_END"):
        return False
    if not validPort(XSEGBD_START, xseg_ports, "XSEGBD_START"):
        return False
    if not validPort(XSEGBD_END, xseg_ports, "XSEGBD_END"):
        return False

    if not XSEGBD_START < XSEGBD_END:
        print red("XSEGBD_START should be less than XSEGBD_END")
        return False
    if not VPORT_START < VPORT_END:
        print red("VPORT_START should be less than VPORT_END")
        return False
#TODO check than no other port is set in the above ranges

    global BLOCKER
    try:
        BLOCKER = available_storage[str(STORAGE)]
    except:
        print red("Invalid storage " + str(STORAGE))
        print "Available storage: \"" + ', "'.join(available_storage) + "\""
        return False

    if STORAGE=="files":
        if FILED_IMAGES and not os.path.isdir(str(FILED_IMAGES)):
             print red("FILED_IMAGES invalid")
             return False
        if FILED_MAPS and not os.path.isdir(str(FILED_MAPS)):
             print red("FILED_PATH invalid")
             return False
        if PITHOS and not os.path.isdir(str(PITHOS)):
             print red("PITHOS invalid ")
             return False
        if PITHOSMAPS and not os.path.isdir(str(PITHOSMAPS)):
             print red("PITHOSMAPS invalid")
             return False
    elif STORAGE=="RADOS":
        #TODO use rados.py to check for pool existance
        pass

    for p in [BLOCKER, MAPPER, VLMC]:
        if not validExec(p):
            print red(p + "is not a valid executable")
            return False

    return True

def construct_peers():
    #these must be in sync with roles
    executables = dict()
    config_opts = dict()
    executables['blockerb'] = BLOCKER
    executables['blockerm'] = BLOCKER
    executables['mapperd'] = MAPPER
    executables['vlmcd'] = VLMC

    if BLOCKER == "pfiled":
        config_opts['blockerb'] = [
                "-p" , str(BPORT), "-g", str(SPEC).encode(), "-n", str(NR_OPS_BLOCKERB),
                 str(PITHOS), str(FILED_IMAGES), "-d",
                "-f", os.path.join(PIDFILE_PATH, "blockerb" + PID_SUFFIX)
                ]
        config_opts['blockerm'] = [
                "-p" , str(MBPORT), "-g", str(SPEC).encode(), "-n", str(NR_OPS_BLOCKERM),
                str(PITHOSMAPS), str(FILED_MAPS), "-d",
                "-f", os.path.join(PIDFILE_PATH, "blockerm" + PID_SUFFIX)
                ]
    elif BLOCKER == "mt-sosd":
        config_opts['blockerb'] = [
                "-p" , str(BPORT), "-g", str(SPEC).encode(), "-n", str(NR_OPS_BLOCKERB),
                 "--pool", str(RADOS_POOL_BLOCKS), "-v", str(VERBOSITY_BLOCKERB),
                 "-d", "--pidfile", os.path.join(PIDFILE_PATH, "blockerb" + PID_SUFFIX),
                 "-l", os.path.join(str(LOGS_PATH), "blockerb" + LOG_SUFFIX),
                 "-t", "3"
                 ]
        config_opts['blockerm'] = [
                "-p" , str(MBPORT), "-g", str(SPEC).encode(), "-n", str(NR_OPS_BLOCKERM),
                 "--pool", str(RADOS_POOL_MAPS), "-v", str(VERBOSITY_BLOCKERM),
                 "-d", "--pidfile", os.path.join(PIDFILE_PATH, "blockerm" + PID_SUFFIX),
                 "-l", os.path.join(str(LOGS_PATH), "blockerm" + LOG_SUFFIX),
                 "-t", "3"
                 ]
    elif BLOCKER == "mt-pfiled":
        config_opts['blockerb'] = [
                "-p" , str(BPORT), "-g", str(SPEC).encode(), "-n", str(NR_OPS_BLOCKERB),
                 "--pithos", str(PITHOS), "--archip", str(FILED_IMAGES),
             "-v", str(VERBOSITY_BLOCKERB),
                 "-d", "--pidfile", os.path.join(PIDFILE_PATH, "blockerb" + PID_SUFFIX),
                 "-l", os.path.join(str(LOGS_PATH), "blockerb" + LOG_SUFFIX),
                 "-t", str(NR_OPS_BLOCKERB), "--prefix", ARCHIP_PREFIX
                 ]
        config_opts['blockerm'] = [
                "-p" , str(MBPORT), "-g", str(SPEC).encode(), "-n", str(NR_OPS_BLOCKERM),
                 "--pithos", str(PITHOSMAPS), "--archip", str(FILED_MAPS),
             "-v", str(VERBOSITY_BLOCKERM),
                 "-d", "--pidfile", os.path.join(PIDFILE_PATH, "blockerm" + PID_SUFFIX),
                 "-l", os.path.join(str(LOGS_PATH), "blockerm" + LOG_SUFFIX),
                 "-t", str(NR_OPS_BLOCKERM), "--prefix", ARCHIP_PREFIX
                 ]
    else:
            sys.exit(-1)

    config_opts['mapperd'] = [
             "-t" , "1", "-p",  str(MPORT), "-mbp", str(MBPORT),
              "-g", str(SPEC).encode(), "-n", str(NR_OPS_MAPPER), "-bp", str(BPORT),
              "--pidfile", os.path.join(PIDFILE_PATH, "mapperd" + PID_SUFFIX),
              "-v", str(VERBOSITY_MAPPER), "-d",
              "-l", os.path.join(str(LOGS_PATH), "mapperd" + LOG_SUFFIX)
              ]
    config_opts['vlmcd'] = [
             "-t" , "1", "-sp",  str(VPORT_START), "-ep", str(VPORT_END),
              "-g", str(SPEC).encode(), "-n", str(NR_OPS_VLMC), "-bp", str(BPORT),
              "-mp", str(MPORT), "-d", "-v", str(VERBOSITY_VLMC),
              "--pidfile", os.path.join(PIDFILE_PATH, "vlmcd" + PID_SUFFIX),
              "-l", os.path.join(str(LOGS_PATH), "vlmcd" + LOG_SUFFIX)
              ]

    for r in roles:
        peers[r] = Peer(executable = executables[r], opts = config_opts[r],
                role = r)

    return peers


def exclusive(fn):
    def exclusive_args(args):
        if not os.path.exists(LOCK_PATH):
            try:
                os.mkdir(LOCK_PATH)
            except OSError, (err, reason):
                print >> sys.stderr, reason
        if not os.path.isdir(LOCK_PATH):
            sys.stderr.write("Locking error: ")
            print >> sys.stderr, LOCK_PATH + " is not a directory"
            return -1;
        lock_file = os.path.join(LOCK_PATH, VLMC_LOCK_FILE)
        while True:
            try:
                fd = os.open(lock_file, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                break;
            except OSError, (err, reason):
                print >> sys.stderr, reason
                if err == errno.EEXIST:
                    time.sleep(0.2)
                else:
                    raise OSError(err, lock_file + ' ' + reason)
        try:
            r = fn(args)
        finally:
            os.close(fd)
            os.unlink(lock_file)
        return r

    return exclusive_args

def loadrc(rc):
    try:
        if rc == None:
            execfile(os.path.expanduser(DEFAULTS), globals())
        else:
            execfile(rc, globals())
    except:
        raise Error("Cannot read config file")

    if not check_conf():
        raise Error("Invalid conf file")

def loaded_modules():
    lines = open("/proc/modules").read().split("\n")
    modules = [f.split(" ")[0] for f in lines]
    return modules

def loaded_module(name):
    return name in loaded_modules()

def load_module(name, args):
    s = "Loading %s " % name
    sys.stdout.write(s.ljust(FIRST_COLUMN_WIDTH))
    modules = loaded_modules()
    if name in modules:
        sys.stdout.write(yellow("Already loaded".ljust(SECOND_COLUMN_WIDTH)))
        sys.stdout.write("\n")
        return
    cmd = ["modprobe", "%s" % name]
    if args:
        for arg in args:
            cmd.extend(["%s=%s" % (arg)])
    try:
        check_call(cmd, shell=False);
    except Exception:
        sys.stdout.write(red("FAILED".ljust(SECOND_COLUMN_WIDTH)))
        sys.stdout.write("\n")
        raise Error("Cannot load module %s. Check system logs" %name)
    sys.stdout.write(green("OK".ljust(SECOND_COLUMN_WIDTH)))
    sys.stdout.write("\n")

def unload_module(name):
    s = "Unloading %s " % name
    sys.stdout.write(s.ljust(FIRST_COLUMN_WIDTH))
    modules = loaded_modules()
    if name not in modules:
        sys.stdout.write(yellow("Not loaded".ljust(SECOND_COLUMN_WIDTH)))
        sys.stdout.write("\n")
        return
    cmd = ["modprobe -r %s" % name]
    try:
        check_call(cmd, shell=True);
    except Exception:
        sys.stdout.write(red("FAILED".ljust(SECOND_COLUMN_WIDTH)))
        sys.stdout.write("\n")
        raise Error("Cannot unload module %s. Check system logs" %name)
    sys.stdout.write(green("OK".ljust(SECOND_COLUMN_WIDTH)))
    sys.stdout.write("\n")

xseg_initialized = False

def initialize_xseg():
    global xseg_initialized
    xseg_initialize()
    xseg_initialized = True

def create_segment():
    #fixme blocking....
    initialize_xseg()
    xconf = xseg_config()
    xseg_parse_spec(str(SPEC), xconf)
    r = xseg_create(xconf)
    if r < 0:
        raise Error("Cannot create segment")

def destroy_segment():
    #fixme blocking....
    try:
        initialize_xseg()
        xconf = xseg_config()
        xseg_parse_spec(str(SPEC), xconf)
        xseg = xseg_join(xconf.type, xconf.name, "posix", cast(0, cb_null_ptrtype))
        if not xseg:
            raise Error("Cannot join segment")
        xseg_leave(xseg)
        xseg_destroy(xseg)
    except Exception as e:
        raise Error("Cannot destroy segment")

def check_running(name, pid = None):
    for p in psutil.process_iter():
        if p.name == name:
            if pid:
                if pid == p.pid:
                    return pid
            else:
                return pid
    return None

def check_pidfile(name):
    pidfile = os.path.join(PIDFILE_PATH, name + PID_SUFFIX)
    pf = None
    try:
        pf = open(pidfile, "r")
        pid = int(pf.read())
        pf.close()
    except:
        if pf:
            pf.close()
        return -1;

    return pid

def start_peer(peer):
    if check_pidfile(peer.role) > 0:
        raise Error("Cannot start peer %s. Peer already running" % peer.role)
    cmd = [peer.executable]+ peer.opts
    s = "Starting %s " % peer.role
    sys.stdout.write(s.ljust(FIRST_COLUMN_WIDTH))
    try:
        check_call(cmd, shell=False);
    except Exception as e:
        print e
        sys.stdout.write(red("FAILED".ljust(SECOND_COLUMN_WIDTH)))
        sys.stdout.write("\n")
        raise Error("Cannot start %s" % peer.role)

    pid = check_pidfile(peer.role)
    if pid < 0 or not check_running(peer.executable, pid):
        sys.stdout.write(red("FAILED".ljust(SECOND_COLUMN_WIDTH)))
        sys.stdout.write("\n")
        raise Error("Couldn't start %s" % peer.role)

    sys.stdout.write(green("OK".ljust(SECOND_COLUMN_WIDTH)))
    sys.stdout.write("\n")

def stop_peer(peer):
    pid = check_pidfile(peer.role)
    if pid < 0:
        pretty_print(peer[2], yellow("not running"))
        return

    s = "Stopping %s " % peer.role
    sys.stdout.write(s.ljust(FIRST_COLUMN_WIDTH))
    i = 0
    while check_running(peer.executable, pid):
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.1)
        i += 1
        if i > 150:
            sys.stdout.write(red("FAILED".ljust(SECOND_COLUMN_WIDTH)))
            sys.stdout.write("\n")
            raise Error("Failed to stop peer %s." % peer.role)
    sys.stdout.write(green("OK".ljust(SECOND_COLUMN_WIDTH)))
    sys.stdout.write("\n")

def peer_running(peer):
    pid = check_pidfile(peer.role)
    if pid < 0:
        pretty_print(peer.role, red('not running'))
        return False

    if not check_running(peer.executable, pid):
        pretty_print(peer.role, yellow("Has valid pidfile but does not seem to be active"))
        return False
    pretty_print(peer.role, green('running'))
    return True


def make_segdev():
    try:
        os.stat(str(CHARDEV_NAME))
        raise Error("Segdev already exists")
    except Error as e:
        raise e
    except:
        pass
    cmd = ["mknod", str(CHARDEV_NAME), "c", str(CHARDEV_MAJOR), str(CHARDEV_MINOR)]
    print ' '.join(cmd)
    try:
        check_call(cmd, shell=False);
    except Exception:
        raise Error("Segdev device creation failed.")

def remove_segdev():
    try:
        os.stat(str(CHARDEV_NAME))
    except OSError, (err, reason):
        if err == errno.ENOENT:
            return
        raise OSError(str(CHARDEV_NAME) + ' ' + reason)
    try:
        os.unlink(str(CHARDEV_NAME))
    except:
        raise Error("Segdev device removal failed.")

def start_peers(peers):
    for m in modules:
        if not loaded_module(m):
            raise Error("Cannot start userspace peers. " + m + " module not loaded")
    for r in roles:
        p = peers[r]
        start_peer(p)

def stop_peers(peers):
    for r in reversed(roles):
        p = peers[r]
        stop_peer(p)

def start(args):
    if args.peer:
        try:
            p = peers[args.peer]
        except KeyError:
            raise Error("Invalid peer %s" % str(args.peer))
        return start_peer(p)

    if args.user:
        return start_peers(peers)

    if status(args) > 0:
        raise Error("Cannot start. Try stopping first")

    try:
        for m in modules:
            load_module(m, None)
        time.sleep(0.5)
        make_segdev()
        time.sleep(0.5)
        create_segment()
        time.sleep(0.5)
        start_peers(peers)
        load_module(xsegbd, xsegbd_args)
    except Exception as e:
        print red(e)
        stop(args)
        raise e


def stop(args):
    if args.peer:
        try:
            p = peers[args.peer]
        except KeyError:
            raise Error("Invalid peer %s" % str(args.peer))
        return stop_peer(p)
    if args.user:
        return stop_peers(peers)
    #check devices
    if vlmc_showmapped(args) > 0:
        raise Error("Cannot stop archipelago. Mapped volumes exist")
    unload_module(xsegbd)
    stop_peers(peers)
    remove_segdev()
    for m in reversed(modules):
        unload_module(m)
        time.sleep(0.3)

def status(args):
    r = 0
    if vlmc_showmapped(args) > 0:
        r += 1
    if loaded_module(xsegbd):
        pretty_print(xsegbd, green('Loaded'))
        r += 1
    else:
        pretty_print(xsegbd, red('Not loaded'))
    for m in reversed(modules):
        if loaded_module(m):
            pretty_print(m, green('Loaded'))
            r += 1
        else:
            pretty_print(m, red('Not loaded'))
    for role in reversed(roles):
        p = peers[role]
        if peer_running(p):
            r += 1
    return r

def restart(args):
    stop(args)
    start(args)

class Xseg_ctx(object):
    ctx = None
    port = None
    portno = None

    def __init__(self, spec, portno):
        initialize_xseg()
        xconf = xseg_config()
        xseg_parse_spec(spec, xconf)
        ctx = xseg_join(xconf.type, xconf.name, "posix", cast(0, cb_null_ptrtype))
        if not ctx:
            raise Error("Cannot join segment")
        port = xseg_bind_port(ctx, portno, c_void_p(0))
        if not port:
            raise Error("Cannot bind to port")
        xseg_init_local_signal(ctx, portno)
        self.ctx = ctx
        self.port = port
        self.portno = portno


    def __del__(self):
        return

    def __enter__(self):
        if not self.ctx:
            raise Error("No segment")
        return self

    def __exit__(self, type_, value, traceback):
        self.shutdown()
        return False

    def shutdown(self):
        if self.ctx:
            xseg_quit_local_signal(self.ctx, self.portno)
            xseg_leave(self.ctx)
        self.ctx = None

class Request(object):
    xseg_ctx = None
    req = None

    def __init__(self, xseg_ctx, dst_portno, targetlen, datalen):
        ctx = xseg_ctx.ctx
        if not ctx:
            raise Error("No context")
        req = xseg_get_request(ctx, xseg_ctx.portno, dst_portno, X_ALLOC)
        if not req:
            raise Error("Cannot get request")
        r = xseg_prep_request(ctx, req, targetlen, datalen)
        if r < 0:
            xseg_put_request(ctx, req, xseg_ctx.portno)
            raise Error("Cannot prepare request")
#        print hex(addressof(req.contents))
        self.req = req
        self.xseg_ctx = xseg_ctx
        return

    def __del__(self):
        if self.req:
            if xq_count(byref(self.req.contents.path)) == 0:
                xseg_put_request(self.xseg_ctx.ctx, self.req, self.xseg_ctx.portno)
        self.req = None
        return False

    def __enter__(self):
        if not self.req:
            raise Error("xseg request not set")
        return self

    def __exit__(self, type_, value, traceback):
        if self.req:
            if xq_count(byref(self.req.contents.path)) == 0:
                xseg_put_request(self.xseg_ctx.ctx, self.req, self.xseg_ctx.portno)
        self.req = None
        return False

    def set_op(self, op):
        self.req.contents.op = op

    def get_op(self):
        return self.req.contents.op

    def set_offset(self, offset):
        self.req.contents.offset = offset

    def get_offset(self):
        return self.req.contents.offset

    def get_size(self):
        return self.req.contents.size

    def set_size(self, size):
        self.req.contents.size = size

    def set_flags(self, flags):
        self.req.contents.flags = flags

    def get_flags(self):
        return self.req.contents.flags

    def set_target(self, target):
        """Sets the target of the request, respecting request's targetlen"""
        if len(target) != self.req.contents.targetlen:
            return False
        c_target = xseg_get_target_nonstatic(self.xseg_ctx.ctx, self.req)
        p_target = create_string_buffer(target)
#        print hex(addressof(c_target.contents))
        memmove(c_target, p_target, len(target))
        return True

    def get_target(self):
        """Return a string to the target of the request"""
        c_target = xseg_get_target_nonstatic(self.xseg_ctx.ctx, self.req)
#        print "target_addr " + str(addressof(c_target.contents))
        return string_at(c_target, self.req.contents.targetlen)

    def set_data(self, data):
        """Sets requests data. Data should be a xseg protocol structure""" 
        if sizeof(data) != self.req.contents.datalen:
            return False
        c_data = xseg_get_data_nonstatic(self.xseg_ctx.ctx, self.req)
        p_data = pointer(data)
        memmove(c_data, p_data, self.req.contents.datalen)

        return True

    def get_data(self, _type):
        """return a pointer to the data buffer of the request, casted to the
        selected type"""
#        print "data addr " +  str(addressof(xseg_get_data_nonstatic(self.xseg_ctx.ctx, self.req).contents))
#        ret = cast(xseg_get_data_nonstatic(self.xseg_ctx.ctx, self.req), _type)
#        print addressof(ret.contents)
#        return ret
        if _type:
            return cast(xseg_get_data_nonstatic(self.xseg_ctx.ctx, self.req),\
                                                                 POINTER(_type))
        else:
            return cast(xseg_get_data_nonstatic(self.xseg_ctx.ctx, self.req), \
                                                                       c_void_p)

    def submit(self):
        """Submit the associated xseg_request"""
        p = xseg_submit(self.xseg_ctx.ctx, self.req, self.xseg_ctx.portno, X_ALLOC)
        if p == NoPort:
            raise Exception
        xseg_signal(self.xseg_ctx.ctx, p)

    def wait(self):
        """Wait until the associated xseg_request is responded, discarding any
        other requests that may be received in the meantime"""
        while True:
            received = xseg_receive(self.xseg_ctx.ctx, self.xseg_ctx.portno, 0)
            if received:
#                print addressof(cast(self.req, c_void_p))
#                print addressof(cast(received, c_void_p))
#                print addressof(self.req.contents)
#                print addressof(received.contents)
                if addressof(received.contents) == addressof(self.req.contents):
#                if addressof(cast(received, c_void_p)) == addressof(cast(self.req, c_void_p)):
                    break
                else:
                    p = xseg_respond(self.xseg_ctx.ctx, received, self.xseg_ctx.portno, X_ALLOC)
                    if p == NoPort:
                        xseg_put_request(self.xseg_ctx.ctx, received,
                                self.xseg_ctx.portno)
                    else:
                        xseg_signal(self.xseg_ctx.ctx, p)
            else:
                xseg_prepare_wait(self.xseg_ctx.ctx, self.xseg_ctx.portno)
                xseg_wait_signal(self.xseg_ctx.ctx, 10000000)
                xseg_cancel_wait(self.xseg_ctx.ctx, self.xseg_ctx.portno)
        return True

    def success(self):
        return bool((self.req.contents.state & XS_SERVED) and not
                (self.req.contents.state & XS_FAILED))

@exclusive
def vlmc_showmapped(args):
    try:
        devices = os.listdir(os.path.join(XSEGBD_SYSFS, "devices/"))
    except:
        if loaded_module(xsegbd):
            raise Error("Cannot list %s/devices/" % XSEGBD_SYSFS)
        else:
            return 0

    print "id\tpool\timage\tsnap\tdevice"
    if not devices:
        print "No volumes mapped\n"
        return 0
    try:
        for f in devices:
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            target = open(XSEGBD_SYSFS + "devices/"+ f + "/target").read().strip()

            print "%s\t%s\t%s\t%s\t%s" % (d_id, '-', target, '-', DEVICE_PREFIX +
            d_id)
    except Exception, reason:
        raise Error(reason)
    return len(devices)

def vlmc_showmapped_wrapper(args):
    vlmc_showmapped(args)


@exclusive
def vlmc_create(args):
    name = args.name[0]
    size = args.size
    snap = args.snap

    if len(name) < 6:
        raise Error("Name should have at least len 6")
    if size == None and snap == None:
        raise Error("At least one of the size/snap args must be provided")

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, MPORT, len(name), sizeof(xseg_request_clone)) as req:
        req.set_op(X_CLONE)
        req.set_size(sizeof(xseg_request_clone))
        req.set_offset(0)
        req.set_target(name)

        xclone = xseg_request_clone()
        if snap:
            xclone.target = snap
            xclone.targetlen = len(snap)
        else:
            xclone.target = ""
            xclone.targetlen = 0
        if size:
            xclone.size = size << 20
        else:
            xclone.size = -1

        req.set_data(xclone)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc creation failed")

@exclusive
def vlmc_snapshot(args):
    # snapshot
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, VPORT_START, len(name), sizeof(xseg_request_snapshot)) as req:
        req.set_op(X_SNAPSHOT)
        req.set_size(sizeof(xseg_request_snapshot))
        req.set_offset(0)
        req.set_target(name)

        xsnapshot = xseg_request_snapshot()
        xsnapshot.target = ""
        xsnapshot.targetlen = 0
        req.set_data(xsnapshot)
        req.submit()
        req.wait()
        ret = req.success()
        if ret:
            reply = string_at(req.get_data(xseg_reply_snapshot).contents.target, 64)
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc snapshot failed")
    sys.stdout.write("Snapshot name: %s\n" % reply)


def vlmc_list(args):
    if STORAGE == "rados":
        import rados
        cluster = rados.Rados(conffile='/etc/ceph/ceph.conf')
        cluster.connect()
        ioctx = cluster.open_ioctx(RADOS_POOL_MAPS)
        oi = rados.ObjectIterator(ioctx)
        for o in oi :
            name = o.key
            if name.startswith(ARCHIP_PREFIX) and not name.endswith('_lock'):
		    print name[len(ARCHIP_PREFIX):]
    elif STORAGE == "files":
        raise Error("Vlmc list not supported for files yet")
    else:
        raise Error("Invalid storage")


@exclusive
def vlmc_remove(args):
    name = args.name[0]

    try:
        for f in os.listdir(XSEGBD_SYSFS + "devices/"):
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            target = open(XSEGBD_SYSFS + "devices/"+ f + "/target").read().strip()
            if target == name:
                raise Error("Volume mapped on device %s%s" % (DEVICE_PREFIX,
								d_id))

    except Exception, reason:
        raise Error(name + ': ' + str(reason))

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, MPORT, len(name), 0) as req:
        req.set_op(X_DELETE)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc removal failed")


@exclusive
def vlmc_map(args):
    if not loaded_module(xsegbd):
        raise Error("Xsegbd module not loaded")
    name = args.name[0]
    prev = XSEGBD_START
    try:
        result = [int(open(XSEGBD_SYSFS + "devices/" + f + "/srcport").read().strip()) for f in os.listdir(XSEGBD_SYSFS + "devices/")]
        result.sort()

        for p in result:
            if p - prev > 1:
               break
            else:
               prev = p

        port = prev + 1
        if port > XSEGBD_END:
            raise Error("Max xsegbd devices reached")
        fd = os.open(XSEGBD_SYSFS + "add", os.O_WRONLY)
        print >> sys.stderr, "write to %s : %s %d:%d:%d" %( XSEGBD_SYSFS +
			"add", name, port, port - XSEGBD_START + VPORT_START, REQS )
        os.write(fd, "%s %d:%d:%d" % (name, port, port - XSEGBD_START + VPORT_START, REQS))
        os.close(fd)
    except Exception, reason:
        raise Error(name + ': ' + str(reason))

@exclusive
def vlmc_unmap(args):
    if not loaded_module(xsegbd):
        raise Error("Xsegbd module not loaded")
    device = args.name[0]
    try:
        for f in os.listdir(XSEGBD_SYSFS + "devices/"):
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            name = open(XSEGBD_SYSFS + "devices/"+ f + "/target").read().strip()
            if device == DEVICE_PREFIX + d_id:
                fd = os.open(XSEGBD_SYSFS + "remove", os.O_WRONLY)
                os.write(fd, d_id)
                os.close(fd)
                return
        raise Error("Device %s doesn't exist" % device)
    except Exception, reason:
        raise Error(device + ': ' + str(reason))

# FIXME:
def vlmc_resize(args):
    if not loaded_module(xsegbd):
        raise Error("Xsegbd module not loaded")

    name = args.name[0]
    size = args.size[0]

    try:

        for f in os.listdir(XSEGBD_SYSFS + "devices/"):
            d_id = open(XSEGBD_SYSFS + "devices/" + f + "/id").read().strip()
            d_name = open(XSEGBD_SYSFS + "devices/"+ f + "/name").read().strip()
            if name == d_name:
                fd = os.open(XSEGBD_SYSFS + "devices/" +  d_id +"/refresh", os.O_WRONLY)
                os.write(fd, "1")
                os.close(fd)

    except Exception, reason:
        raise Error(name + ': ' + str(reason))

@exclusive
def vlmc_lock(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    name = ARCHIP_PREFIX + name

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, MBPORT, len(name), 0) as req:
        req.set_op(X_ACQUIRE)
        req.set_size(0)
        req.set_offset(0)
        req.set_flags(XF_NOSYNC)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc lock failed")
    else:
        sys.stdout.write("Volume locked\n")

@exclusive
def vlmc_unlock(args):
    name = args.name[0]
    force = args.force

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    name = ARCHIP_PREFIX + name

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, MBPORT, len(name), 0) as req:
        req.set_op(X_RELEASE)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        if force:
            req.set_flags(XF_NOSYNC|XF_FORCE)
        else:
            req.set_flags(XF_NOSYNC)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc unlock failed")
    else:
        sys.stdout.write("Volume unlocked\n")

@exclusive
def vlmc_open(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, VPORT_START, len(name), 0) as req:
        req.set_op(X_OPEN)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc open failed")
    else:
        sys.stdout.write("Volume opened\n")

@exclusive
def vlmc_close(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, VPORT_START, len(name), 0) as req:
        req.set_op(X_CLOSE)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc close failed")
    else:
        sys.stdout.write("Volume closed\n")

@exclusive
def vlmc_info(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    ret = False
    xseg_ctx = Xseg_ctx(SPEC, VTOOL)
    with Request(xseg_ctx, MPORT, len(name), 0) as req:
        req.set_op(X_INFO)
        req.set_size(0)
        req.set_offset(0)
        req.set_target(name)
        req.submit()
        req.wait()
        ret = req.success()
        if ret:
            size = req.get_data(xseg_reply_info).contents.size
    xseg_ctx.shutdown()
    if not ret:
        raise Error("vlmc info failed")
    else:
        sys.stdout.write("Volume %s: size: %d\n" % (name, size) )

def vlmc_mapinfo(args):
    name = args.name[0]

    if len(name) < 6:
        raise Error("Name should have at least len 6")

    if STORAGE == "rados":
        import rados
        cluster = rados.Rados(conffile=CEPH_CONF_FILE)
        cluster.connect()
        ioctx = cluster.open_ioctx(RADOS_POOL_MAPS)
        BLOCKSIZE = 4*1024*1024
        try:
            mapdata = ioctx.read(ARCHIP_PREFIX + name, length=BLOCKSIZE)
        except Exception:
            raise Error("Cannot read map data")
        if not  mapdata:
            raise Error("Cannot read map data")
        pos = 0
        size_uint32t = sizeof(c_uint32)
        version = unpack("<L", mapdata[pos:pos+size_uint32t])[0]
        pos += size_uint32t
        size_uint64t = sizeof(c_uint64)
        size = unpack("Q", mapdata[pos:pos+size_uint64t])[0]
        pos += size_uint64t
        blocks = size / BLOCKSIZE
        nr_exists = 0
        print ""
        print "Volume: " + name
        print "Version: " + str(version)
        print "Size: " + str(size)
        for i in range(blocks):
            exists = bool(unpack("B", mapdata[pos:pos+1])[0])
            if exists:
                nr_exists += 1
            pos += 1
            block = hexlify(mapdata[pos:pos+32])
            pos += 32
            if args.verbose:
                print block, exists
        print "Actual disk usage: " + str(nr_exists * BLOCKSIZE),
        print '(' + str(nr_exists) + '/' + str(blocks) + ' blocks)'

    elif STORAGE=="files":
        raise Error("Mapinfo for file storage not supported")
    else:
        raise Error("Invalid storage")

def archipelago():
    parser = argparse.ArgumentParser(description='Archipelago tool')
    parser.add_argument('-c', '--config', type=str, nargs='?', help='config file')
    parser.add_argument('-u', '--user',  action='store_true', default=False , help='affect only userspace peers')
    subparsers = parser.add_subparsers()

    start_parser = subparsers.add_parser('start', help='Start archipelago')
    start_parser.set_defaults(func=start)
    start_parser.add_argument('peer', type=str, nargs='?',  help='peer to start')

    stop_parser = subparsers.add_parser('stop', help='Stop archipelago')
    stop_parser.set_defaults(func=stop)
    stop_parser.add_argument('peer', type=str, nargs='?', help='peer to stop')

    status_parser = subparsers.add_parser('status', help='Archipelago status')
    status_parser.set_defaults(func=status)

    restart_parser = subparsers.add_parser('restart', help='Restart archipelago')
    restart_parser.set_defaults(func=restart)
    restart_parser.add_argument('peer', type=str, nargs='?', help='peer to restart')

    return parser

def vlmc():
    parser = argparse.ArgumentParser(description='vlmc tool')
    parser.add_argument('-c', '--config', type=str, nargs='?', help='config file')
    subparsers = parser.add_subparsers()

    create_parser = subparsers.add_parser('create', help='Create volume')
    #group = create_parser.add_mutually_exclusive_group(required=True)
    create_parser.add_argument('-s', '--size', type=int, nargs='?', help='requested size in MB for create')
    create_parser.add_argument('--snap', type=str, nargs='?', help='create from snapshot')
    create_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')
    create_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    create_parser.set_defaults(func=vlmc_create)

    remove_parser = subparsers.add_parser('remove', help='Delete volume')
    remove_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    remove_parser.set_defaults(func=vlmc_remove)
    remove_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    rm_parser = subparsers.add_parser('rm', help='Delete volume')
    rm_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    rm_parser.set_defaults(func=vlmc_remove)
    rm_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    map_parser = subparsers.add_parser('map', help='Map volume')
    map_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    map_parser.set_defaults(func=vlmc_map)
    map_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    unmap_parser = subparsers.add_parser('unmap', help='Unmap volume')
    unmap_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    unmap_parser.set_defaults(func=vlmc_unmap)
    unmap_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    showmapped_parser = subparsers.add_parser('showmapped', help='Show mapped volumes')
    showmapped_parser.set_defaults(func=vlmc_showmapped_wrapper)
    showmapped_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    list_parser = subparsers.add_parser('list', help='List volumes')
    list_parser.set_defaults(func=vlmc_list)
    list_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    snapshot_parser = subparsers.add_parser('snapshot', help='snapshot volume')
    #group = snapshot_parser.add_mutually_exclusive_group(required=True)
    snapshot_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')
    snapshot_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    snapshot_parser.set_defaults(func=vlmc_snapshot)

    ls_parser = subparsers.add_parser('ls', help='List volumes')
    ls_parser.set_defaults(func=vlmc_list)
    ls_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    resize_parser = subparsers.add_parser('resize', help='Resize volume')
    resize_parser.add_argument('-s', '--size', type=int, nargs=1, help='requested size in MB for resize')
    resize_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    resize_parser.set_defaults(func=vlmc_resize)
    resize_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    open_parser = subparsers.add_parser('open', help='open volume')
    open_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    open_parser.set_defaults(func=vlmc_open)
    open_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    close_parser = subparsers.add_parser('close', help='close volume')
    close_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    close_parser.set_defaults(func=vlmc_close)
    close_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    lock_parser = subparsers.add_parser('lock', help='lock volume')
    lock_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    lock_parser.set_defaults(func=vlmc_lock)
    lock_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    unlock_parser = subparsers.add_parser('unlock', help='unlock volume')
    unlock_parser.add_argument('name', type=str, nargs=1, help='volume/device name')
    unlock_parser.add_argument('-f', '--force',  action='store_true', default=False , help='break lock')
    unlock_parser.set_defaults(func=vlmc_unlock)
    unlock_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    info_parser = subparsers.add_parser('info', help='Show volume info')
    info_parser.add_argument('name', type=str, nargs=1, help='volume name')
    info_parser.set_defaults(func=vlmc_info)
    info_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')

    map_info_parser = subparsers.add_parser('mapinfo', help='Show volume map_info')
    map_info_parser.add_argument('name', type=str, nargs=1, help='volume name')
    map_info_parser.set_defaults(func=vlmc_mapinfo)
    map_info_parser.add_argument('-p', '--pool', type=str, nargs='?', help='for backwards compatiblity with rbd')
    map_info_parser.add_argument('-v', '--verbose',  action='store_true', default=False , help='')

    return parser

def cli():
    # parse arguments and discpatch to the correct func
    try:
        parser_func = {
            'archipelago' : archipelago,
            'vlmc'        : vlmc,
        }[os.path.basename(sys.argv[0])]
        parser = parser_func()
    except Exception as e:
        sys.stderr.write("Invalid basename\n")
        return -1

    args = parser.parse_args()
    loadrc(args.config)
    if parser_func == archipelago:
        peers = construct_peers()
	xsegbd_args = [('start_portno', str(XSEGBD_START)), ('end_portno',
		str(XSEGBD_END))]

    try:
        args.func(args)
        return 0
    except Error as e:
        print red(e)
        return -1

if __name__ == "__main__":
    sys.exit(cli())
