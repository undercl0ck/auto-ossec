#!/usr/bin/python
#
# This is the ossec auto enrollment server daemon. This should be put under supervisor to ensure health and stability.
#
#
# Works with Alienvault and Standlone OSSEC installs
#
# Will listen on port 9654 for an incoming challege
#
#
import socketserver
from threading import Thread
import subprocess
import sys

# check python crypto library
try:
    from Crypto.Cipher import AES

except ImportError:
    print(
        "[!] ERROR: python-crypto not installed. Run 'apt-get install python-pycrypto pexpect' to fix.")
    sys.exit()

import base64
import _thread

# check pexpect library
try:
    import pexpect
except ImportError:
    print("[!] ERROR: pexpect not installed. Run apt-get install pexpect to fix.")
    sys.exit()

import time
import socket
import os


class service(socketserver.BaseRequestHandler):

    def handle(self):
        # parse OSSEC hids client certificate
        def parse_client(hostname, ipaddr):
            child = pexpect.spawn("/var/ossec/bin/manage_agents")
            child.expect("Choose your action")
            child.sendline("a")
            child.expect("for the new agent")
            child.sendline(hostname)
            i = child.expect(
                ['IP Address of the new agent', 'already present'])

            # if we haven't already added the hostname
            if i == 0:
                child.sendline(ipaddr)
                i = child.expect(['for the new agent', 'Invalid IP'])
                if i == 0:
                    child.sendline("")
                    for line in child:
                        line = line.decode('utf-8')
                        # pull id
                        if "[" in line:
                            id = line.replace(
                                "[", "").replace("]", "").replace(":", "").rstrip()
                        break
                    child.expect("Confirm adding it?")
                    child.sendline("y")
                    child.sendline("")
                    child.sendline("q")
                    child.close()
                    child = pexpect.spawn(
                        "/var/ossec/bin/manage_agents -e %s" % (id))
                    for line in child:
                        key = line.rstrip()

                    return key

                if i == 1:
                    print("[!] Server responded with not supporting wildcards. AlienVault appears to support this however standard OSSEC does not.")
                    print("[!] Unable to add host based on wildcard certificates on this system.")
                    return "star_issue"

            # if we have a duplicate hostname
            if i == 1:
                child.close()
                child = pexpect.spawn("/var/ossec/bin/manage_agents -l")
                for line in child:
                    line = line.decode('utf-8').rstrip()
                    if hostname in line:
                        id = line.split(",")[0].replace(
                            "ID: ", "").replace("   ", "").rstrip()
                        break
                child.close()
                subprocess.Popen("/var/ossec/bin/manage_agents -r %s" %
                                 (id), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True).wait()
                return 0

        # main AES encrypt and decrypt function with 32 block size padding
        def aescall(secret, data, format):

            # padding and block size
            PADDING = '{'
            BLOCK_SIZE = 32

            # one-liner to sufficiently pad the text to be encrypted
            pad = lambda s: s + (BLOCK_SIZE - len(s) % BLOCK_SIZE) * PADDING

            # random value here to randomize builds
            a = 50 * 5

            # one-liners to encrypt/encode and decrypt/decode a string
            # encrypt with AES, encode with base64
            EncodeAES = lambda c, s: bytes(base64.b64encode(c.encrypt(pad(s))))
            DecodeAES = lambda c, e: c.decrypt(base64.b64decode(e)) # , 'utf-8')
            cipher = AES.new(secret)

            if format == "encrypt":
                aes = EncodeAES(cipher, data)
                return str(aes)

            if format == "decrypt":
                aes = DecodeAES(cipher, data)
                aes = aes.decode('utf-8')
                return str(aes)

        # recommend changing this - if you do, change auto_ossec.py as well - -
        # would recommend this is the default published to git
        secret = "(3j+-sa!333hNA2u3h@*!~h~2&^lk<!B"
        print("Client connected with ", self.client_address)
        try:
            data = self.request.recv(1024)
            if data != "":
                try:
                    data = aescall(secret, data, "decrypt")

                    # if this section clears -we know that it is a legit
                    # request, has been decrypted and we're ready to rock
                    if "BDSOSSEC" in data:

                        # if we are using star IP addresses
                        if "BDSOSSEC*" in data:
                            star = 1
                        else:
                            star = 0

                        # write a lock file to check later on with our threaded
                        # process to restart OSSEC if needed every 10 minutes -
                        # if lock file is present then it will trigger a
                        # restart of OSSEC server
                        if not os.path.isfile("lock"):
                            filewrite = open("lock", "w")
                            filewrite.write("lock")
                            filewrite.close()

                        # strip identifier
                        data = data.replace(
                            "BDSOSSEC*", "").replace("BDSOSSEC", "").replace("{", "")
                        hostname = data

                        # pull the true IP, not the NATed one if they are using
                        # VMWare
                        if star == 0:
                            ipaddr = self.client_address[0]
                        else:
                            ipaddr = "*"

                        # here if the hostname was already used, we need to
                        # remove it and call it again
                        data = parse_client(hostname, ipaddr)
                        if data == 0:
                            data = parse_client(hostname, ipaddr)

                        if data == "star_issue":
                            print("[*] Sending star issue to client to report.")

                        else:
                            print("[*] Provisioned new key for hostname: %s with IP of: %s" %
                                 (hostname, ipaddr))
                        data = aescall(secret, data, "encrypt")
                        print("[*] Sending new key to %s: " % (ipaddr) + data)
                        self.request.send(data.encode('utf-8'))

                except Exception as e:
                    print(e)
                    pass

        except Exception as e:
            print(e)
            pass

        print("Pairing complete. Terminating connection to client.")
        self.request.close()

# this waits 5 minutes to check if new ossec agents have been deployed, if
# so it restarts the server
def ossec_monitor():
    while 1:
        time.sleep(300)
        if os.path.isfile("lock"):
            os.remove("lock")
            print(
                "[*] New OSSEC agent added - triggering restart of service to add..")
            subprocess.Popen("service ossec restart", stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=True).wait()


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

print("[*] The auto enrollment OSSEC Server is now listening on 9654")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# set is so that when we cancel out we can reuse port
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# bind to all interfaces on port 10900

ThreadedTCPServer.allow_reuse_address = True
t = ThreadedTCPServer(('', 9654), service)
# start the server and listen forever
try:
    # start a threaded counter
    _thread.start_new_thread(ossec_monitor, ())

    t.serve_forever()

except KeyboardInterrupt:
    print("[*] Exiting the automatic enrollment OSSEC daemon")
