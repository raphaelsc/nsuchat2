#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This file is part of PySafeChat.
# This module contains the functions related to establishing connections.
#
# Copyright (©) 2014 Marcel Ribeiro Dantas
#
# <mribeirodantas at fedoraproject.org>
#
# PySafeChat is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# PySafeChat is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PySafeChat. If not, see <http://www.gnu.org/licenses/>.

import socket
import select
import sys

import pickle
from Crypto.Cipher import AES

from os import urandom
import base64

from server import create_socket
from apdu import *

from time import gmtime, strftime

SOCKET_LIST = []         # List of sockets connected to the server
VERSION = 0.1            # Client Application Protocol Version
nickname = ''            # User nickname
serverPort = ''          # Port to connect
FIRST_READING = True     # First reading
MAX_BUFFER = 1024
BLOCK_SIZE = 16                  # AES needs a BLOCK_SIZE Of 16, 24 or 32
SYMM_KEY = urandom(BLOCK_SIZE)   # Symmetric Key
CIPHER = AES.new(SYMM_KEY)       # AES Cipher using the Symmetric Key

# the character used for padding--with a block cipher such as AES, the value
# you encrypt must be a multiple of BLOCK_SIZE in length.  This character is
# used to ensure that your value is always a multiple of BLOCK_SIZE
PADDING = '{'

# one-liner to sufficiently pad the text to be encrypted
pad = lambda s: s + (BLOCK_SIZE - len(s) % BLOCK_SIZE) * PADDING

# one-liners to encrypt/encode and decrypt/decode a string
# encrypt with AES, encode with base64
EncodeAES = lambda c, s: base64.b64encode(c.encrypt(pad(s)))
DecodeAES = lambda c, e: c.decrypt(base64.b64decode(e)).rstrip(PADDING)


def prompt(who='', msg=''):
    if len(who) == 0:
        sys.stdout.write(strftime('[%H:%M:%S] ', gmtime()) + '<You> ')
        sys.stdout.flush()
    else:
        if '[Server]' in who:
            sys.stdout.write(strftime('[%H:%M:%S] ', gmtime()) + who
                         + msg)
            sys.stdout.flush()
        else:
            sys.stdout.write(strftime('\n[%H:%M:%S] ', gmtime()) + who
                         + msg)
            sys.stdout.flush()


def message(target_socket, message):
    """Takes a target socket and a message and sends a message to the specified
    socket. This function is supposed to be only used for server notificatoins
    to specific users. For all users, check broadcast.__doc__"""
    # Send the message only to the target
    for sockfd in SOCKET_LIST:
        if sockfd == target_socket:
            try:
                sockfd.send(message)
            # broken socket connection may be, chat client pressed ctrl+c
            # for example
            except socket.error, msg:
                print 'Failed to send message. Error code: ' + str(msg[0]) +\
                      ' Error' + ' message: ' + msg[1]
                sockfd.close()
                SOCKET_LIST.remove(sockfd)
                sys.exit()

if __name__ == "__main__":
    if len(sys.argv) == 1:
        try:
            print "Please, answer the following questions."
            while len(nickname) == 0 or nickname[0] == ' ':
                nickname = raw_input("Nickname: ")
            server_ip = raw_input("Server IP/Name: ")
            if server_ip == '':
                print 'Using localhost...'
                server_ip = '0.0.0.0'
            while len(serverPort) == '' or serverPort == '':
                serverPort = raw_input("Server Port: ")
            serverPort = int(serverPort)
        except KeyboardInterrupt:
            print "\nQuitting.."
            sys.exit()
    elif len(sys.argv) != 3:
        print 'Usage: python client.py nickname server:port'
        sys.exit()
    else:
        try:
            nickname = sys.argv[1]
            serverPort = sys.argv[2]
            # If server was informed in the commandline argument
            if len(serverPort.split(':')) == 2:
                serverPort = int(serverPort.split(':')[1])
                server_ip = serverPort.split(':')[0]
            else:
                serverPort = int(serverPort)
                server_ip = '0.0.0.0'
        except ValueError:
            print 'Server port must be an integer.'
            sys.exit()

    if serverPort > 65535:
        print 'Server port must be lower than 65535.'
    else:
        client_socket = create_socket(serverPort, server_ip)
        print 'Connected to chat server'

    while True:
        try:
            SOCKET_LIST = [sys.stdin, client_socket]
            # Get the list sockets which are readable
            read_sockets, write_sockets, error_sockets = select.select(
                                                        SOCKET_LIST, [], [])
        except KeyboardInterrupt:
            print "\nQuitting..."
            h_msg = DISCONNECT
            msg_enc = EncodeAES(CIPHER, h_msg)
            client_socket.send(msg_enc)
            sys.exit()
        for sock in read_sockets:
            #incoming message from remote server
            if sock == client_socket:
                data = sock.recv(MAX_BUFFER)
                # Server disconnected.
                if not data:
                    print '\nDisconnected from chat server'
                    sys.exit()
                # Proper information arrived.
                else:
                    if FIRST_READING:  # Receiving Public Key from Server
                        print '\n[Symmetric Key Exchange started]'
                        print '--> Receiving Public Key from Server...'
                        public_key = pickle.loads(data)
                        SYMM_KEY_enc = public_key.encrypt(SYMM_KEY, 32)
                        print '--> Sending encrypted Symmetric Key to server...'
                        message(sock, pickle.dumps(SYMM_KEY_enc))
                        FIRST_READING = False
                    else:  # Receiving data encrypted with Symmetric Key
                        #print '--> Decrypting incoming data...'
                        decoded = DecodeAES(CIPHER, data)
                        if decoded[:2] == SYMM_ACK:
                            print '--> Symmetric key exchange was successful.'
                            print '[Symmetric Key Exchange ended]\n'
                            # Request Server Information
                            data_enc = EncodeAES(CIPHER, REQ_SERVER_INFO)
                            # Send REQ_SERVER_INFO to server
                            message(sock, data_enc)
                        elif decoded[:2] == SHARE_SERVER_INFO:
                            data = decoded.split(',')
                            print '\nChat server configuration:'
                            print 'Maximum number of connected users: ' +\
                                   data[1]
                            print 'Maximum nickname length: ' + data[2]
                            print 'Maximum message length: ' + data[3]
                            print 'Protocol version: ' + data[4] + '\n'
                            if data[4] == str(VERSION):
                                if len(nickname) <= int(data[2]):
                                    # Send CHANGE_NICKNAME to server
                                    msg = CHANGE_NICKNAME + nickname
                                    msg_enc = EncodeAES(CIPHER, msg)
                                    message(sock, msg_enc)
                                else:
                                    print 'Sorry, your nickname is too long.\n'
                                    sys.exit()
                            else:
                                print 'Sorry, version mismatch ocurred.\n' +\
                                'Server Application Protocol Version: ' +\
                                 data[4] + '\nClient Application Protocol' +\
                                 ' Version: ' + str(VERSION)
                                sys.exit()
                        elif decoded[:2] == ALREADY_USED:
                            print 'Nickname already in use.'
                            print 'Exitting...'
                            sys.exit()
                        elif decoded[:2] == WELCOME:
                            print 'Welcome to the server ' + nickname + '.'
                            prompt()
            # Client user entered text
            else:
                try:
                    msg = sys.stdin.readline()
                    if '/clear' in msg:
                        # ANSI Way
                        # Clear the window: print chr(27) + "[2J"
                        # Move cursor to top of the window \x1b[H
                        sys.stderr.write("\x1b[2J\x1b[H")
                        prompt()
                    # Broadcast data
                    else:
                        # Adding BROADCAST header
                        h_msg = BROADCAST + msg
                        msg_enc = EncodeAES(CIPHER, h_msg)
                        client_socket.send(msg_enc)
                        # If a command has just been run, do not show prompt
                        prompt()
                except (KeyboardInterrupt, IndexError):
                    print '\nQuitting...'
                    h_msg = DISCONNECT
                    msg_enc = EncodeAES(CIPHER, h_msg)
                    client_socket.send(msg_enc)
                    sys.exit()