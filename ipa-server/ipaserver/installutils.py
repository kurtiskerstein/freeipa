# Authors: Simo Sorce <ssorce@redhat.com>
#
# Copyright (C) 2007    Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; version 2 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
#

import logging
import socket
import errno
import getpass
import os
import re
import fileinput
import sys
import time
import struct
import fcntl

from ipa import ipautil
from ipa import dnsclient

def get_fqdn():
    fqdn = ""
    try:
        fqdn = socket.getfqdn()
    except:
        try:
            fqdn = socket.gethostname()
        except:
            fqdn = ""
    return fqdn

def reverse_ip(ipaddr):
    i = ipaddr.split('.')
    i.reverse()
    return '.'.join(i)
   
def verify_fqdn(host_name):
    if len(host_name.split(".")) < 2 or host_name == "localhost.localdomain":
        raise RuntimeError("Invalid hostname: " + host_name)

    # Verify that it is a DNS A record
    rs = dnsclient.query(host_name+".", dnsclient.DNS_C_IN, dnsclient.DNS_T_A)
    if len(rs) == 0:
        raise RuntimeError("hostname %s is not found or is not a DNS A record" % host_name)

    # Compare the forward and reverse
    forward = rs[0].dns_name

    addr = socket.inet_ntoa(struct.pack('=L',rs[0].rdata.address))
    addr = addr + ".in-addr.arpa."

    rs = dnsclient.query(addr, dnsclient.DNS_C_IN, dnsclient.DNS_T_PTR)
    if len(rs) == 0:
        raise RuntimeError("Cannot find PTR record for %s" % addr)
    reverse = rs[0].rdata.ptrdname

    if forward != reverse:
        raise RuntimeError("The DNS forward record %s does not match the reverse lookup %s" % (forward, reverse))

    # Look in /etc/hosts for this IP
    try:
        fd = open("/etc/hosts", "r")
    except:
        raise RuntimeError("Unable to open /etc/hosts for reading. Check file permissions.")

    p = re.compile('([a-zA-Z0-9\.:]+)\s+([a-zA-Z0-9\.\-]+)')
    while True:
        line = fd.readline()
        if not line: break
        if len(line) > 0 and line[0] == "#":
           continue   
        m = p.match(line)
        hname = None
        try:
            if m.group(1) == ipaddr:
                hname = m.group(2) + "."
        except:
            pass
        if hname and hname != forward:
            fd.close()
            raise RuntimeError("The IP address in /etc/hosts defines the hostname as '%s' but DNS says it is '%s'. The fully-qualified hostname needs to appear on the list first in /etc/hosts" % (hname, forward))

    fd.close()

def port_available(port):
    """Try to bind to a port on the wildcard host
       Return 1 if the port is available
       Return 0 if the port is in use
    """
    rv = 1

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        fcntl.fcntl(s, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
        s.bind(('', port))
        s.close()
    except socket.error, e:
        if e[0] == errno.EADDRINUSE:
            rv = 0

    if rv:
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            fcntl.fcntl(s, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
            s.bind(('', port))
            s.close()
        except socket.error, e:
            if e[0] == errno.EADDRINUSE:
                rv = 0

    return rv

def standard_logging_setup(log_filename, debug=False):
    # Always log everything (i.e., DEBUG) to the log
    # file.
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s %(message)s',
                        filename=log_filename,
                        filemode='w')

    console = logging.StreamHandler()
    # If the debug option is set, also log debug messages to the console
    if debug:
        console.setLevel(logging.DEBUG)
    else:
        # Otherwise, log critical and error messages
        console.setLevel(logging.ERROR)
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

def read_password(user):
    correct = False
    pwd = ""
    while not correct:
        pwd = getpass.getpass(user + " password: ")
        if not pwd:
            continue
        if len(pwd) < 8:
            print "Password must be at least 8 characters long"
            continue
        pwd_confirm = getpass.getpass("Password (confirm): ")
        if pwd != pwd_confirm:
            print "Password mismatch!"
            print ""
        else:
            correct = True
    print ""
    return pwd

def update_file(filename, orig, subst):
    if os.path.exists(filename):
        pattern = "%s" % re.escape(orig)
        p = re.compile(pattern)
        for line in fileinput.input(filename, inplace=1):
            if not p.search(line):
                sys.stdout.write(line)
            else:
                sys.stdout.write(p.sub(subst, line))
        fileinput.close()
        return 0
    else:
        print "File %s doesn't exist." % filename
        return 1

def kadmin(command):
    ipautil.run(["/usr/kerberos/sbin/kadmin.local", "-q", command])

def kadmin_addprinc(principal):
    kadmin("addprinc -randkey " + principal)

def kadmin_modprinc(principal, options):
    kadmin("modprinc " + options + " " + principal)

def create_keytab(path, principal):
    try:
        if ipautil.file_exists(path):
            os.remove(path)
    except os.error:
        logging.critical("Failed to remove %s." % path)

    kadmin("ktadd -k " + path + " " + principal)

