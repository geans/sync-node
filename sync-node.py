# -*- coding: utf-8 -*-

import socket
import json
from pathlib import Path
from enum import Enum
from time import time
from threading import Thread
from subprocess import check_output

# PATH TO WORK
MYPATH = '.'

# Constants
INTERFACE = socket.AF_INET     # interface type
TRANSPORT = socket.SOCK_STREAM # transport type: aka TCP
timesold =  lambda path: path.stat().st_mtime
newest = lambda t1, t2: t1 if t1 < t2 else t2

class Status(Enum):
    ADD_FILE = '1'
    CHANGE = '2'
    DELETE = '3'
    ADD_PATH = '4'

class Command:
    HELLO = b'1'
    PUBLICATION = b'2'
    GET = b'3'
    size = 1

DEBUG = True
def mdebug(*objects, sep=' ', end='\n'):
    if DEBUG:
        for o in objects:
            print(o, end=sep)
        print(end=end)

class SyncNode:
    port_listen = 65432
    external_reports = []

    def __init__(self, directory):
        self.directory = Path(directory)  # root directory to sync
        self.main_map = {}  # TODO init loading from file
        self.friends = []  # list of IPs
        self.internal_reports = []
        self.myip = None
        
        self.search_friend()
        self.thread_listen = Thread(target=SyncNode.listen_mode)
        self.thread_listen.start()
    
    def run(self):
        self.check_external_updates()
        self.check_my_updates()
        self.publish_updates()    
    
    def check_external_updates(self):
        while SyncNode.external_reports:
            reports = SyncNode.external_reports.pop(0)
            for r in reports.split('\n'):
                path, t_old, status, friend_ip = r.split(' ')

            if status == Status.ADD_PATH:
                if path in self.main_map:
                    if newest(t_old, self.main_map[path]) == t_old:
                        if not Path(path).is_dir():
                            raise Exception('Falha na sincronização: Pasta com mesmo nome de arquivo. Pasta recebida é mais recente.')
              else:
                Path(path).mkdir()

            elif status == Status.ADD_FILE:
                if path in self.main_map:
                    if newest(t_old, self.main_map[path]) == t_old:
                        if Path(path).is_dir():
                            raise Exception('Falha na sincronização: Pasta com mesmo nome de arquivo. Arquivo recebida é mais recente.')
                else:
                    self.get_file_from_friend(path, friend_ip)

            elif status == Status.CHANGE:
                pass # TODO

            elif status == Status.DELETE:
                pass # TODO

            else:
                raise Exception('Status desconhecido.')
    
    def check_my_updates(self):
        current_map = self.directory_tree_status(self.directory)
        reports = ''
        add_report = lambda path, t_old, status: '{} {} {} {}\n'.format(path, t_old, status, self.myip)
        
        # Compare path added or changed
        for path in current_map:
            if path not in self.main_map:
              status = Status.ADD_PATH if Path(path).is_dir() else Status.ADD_FILE
              reports += add_report(path, current_map[path], status)
            elif current_map[path] > self.main_map[path]:
              reports += add_report(path, current_map[path], Status.CHANGE)
        
        # Compare path deleted
        for path in self.main_map:
            if path not in current_map:
                reports += add_report(path, self.main_map[path], Status.DELETE)
        
        self.internal_reports.append(reports)
        return reports

    def publish_updates(self):
        while self.internal_reports:
            report = self.internal_reports.pop(0)
            for friend_ip in self.friends:
                friend = socket.socket(INTERFACE, TRANSPORT)
                try:
                    friend.connect((friend_ip, SyncNode.port_listen))
                    msg = Command.PUBLICATION + report.encode()
                    friend.sendall(msg)
                except Exception as e:
                    pass
                    
    def get_file_from_friend(self, path, friend_ip):
        friend = socket.socket(INTERFACE, TRANSPORT)
        try:
            friend.connect((friend_ip, SyncNode.port_listen))
            msg = Command.GET + path.encode()
            friend.sendall(msg)
            tmp = friend.recv(1024)
            data = tmp
            while tmp:
                data += tmp
                tmp = friend.recv(1024)
            
            # Ensure existing directory
            path_split = Path(path).as_posix().split('/')
            with Path('/'.join(path_split[:-1])) as d:
                if not d.exists():
                    d.mkdir()
            
            with open(path, 'w') as f:
                f.write(data.decode())
                
        except Exception as e:
            pass
    
    #@staticmethod
    def directory_tree_status(self, dirname, traversed = [], results = {}): 
        traversed.append( dirname )
        if dirname.is_dir():
            for path in dirname.iterdir():
                results[path.name] = timesold(path)
                if path not in traversed:
                    self.directory_tree_status(path, traversed, results)
        return results
    
    def search_friend(self):
        ip = check_output(['hostname', '--all-ip-addresses'])
        self.myip = ip = ip.split()[0].decode()
        mdebug('My ip:', ip)
        ip_parts = ip.split('.')
        base_ip = ip_parts[0] + '.' + ip_parts[1] + '.' + ip_parts[2] + '.'
        for i in range(1,255):
            target_ip = base_ip + str(i)
            if target_ip == ip or target_ip in self.friends:
                continue
            friend = socket.socket(INTERFACE, TRANSPORT)
            try:
            friend.connect((target_ip, SyncNode.port_listen))
            friend.sendall(Command.HELLO)
            response = friend.recv(1024)
            mdebug(' Response:', response)
            if response == Command.HELLO:
                self.friends.append(target_ip)
                mdebug('New friend:', target_ip)
            except Exception as e:
                pass
            friend.close()
    
    @staticmethod
    def listen_mode():
        mdebug('Init server')
        s = socket.socket(INTERFACE, TRANSPORT)
        s.bind(('', SyncNode.port_listen))
        s.listen(10)  # number of conexions in queue
        conn, addr = s.accept()
        mdebug('Connected by', addr)
        while 1:
            data = conn.recv(Command.size)
            if not data: break
            if data == Command.HELLO:
                conn.send(Command.HELLO)
            elif data == Command.PUBLICATION:
                SyncNode.receiver_publication(conn)
            elif data == Command.GET:
                tmp = conn.recv(1024)
                path = tmp
                while tmp:
                    path += tmp
                    tmp = conn.recv(1024)
                SyncNode.send_file_to_friend(conn, path)
        conn.close()
    
    @staticmethod
    def receiver_publication(conn):
        report = ''
        tmp = conn.recv(1024)
        while tmp:
            report += str(tmp)
            tmp = conn.recv(1024)
        SyncNode.external_reports.append(report)
    
    @staticmethod
    def send_file_to_friend(conn, path):
        file = Path(path)
        if not file.exists():
            # raise Exception('Erro: arquivo solicitado não existe.' + path)
            mdebug('Erro: arquivo solicitado não existe: ' + path)
        elif file.is_dir():
            mdebug('Erro: caminho solicitado é um diretório e não um arquivo: ' + path)
        else:
            with file.open() as f:
                data = f.read()
                f.close()
                conn.sendall(data)


if __name__ == '__main__':
    
    # teste: encontrar "friends"
    n2 = SyncNode(Path(MYPATH))
    process = Thread(target=SyncNode.listen_mode)
    process.start()
    n2.search_friend()
    process.join()
