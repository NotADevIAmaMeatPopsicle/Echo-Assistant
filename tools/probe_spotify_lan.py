"""Verify Echo's Spotify HTTP and DNS-SD path from another LAN host, without pairing."""
from backend import deployment
import argparse
import ipaddress
import json
import secrets
import socket
import struct
import time
import urllib.request


def dns_name(packet, offset):
    labels=[]; end=None; visited=set()
    for _ in range(128):
        if offset in visited: raise ValueError('DNS name loop')
        visited.add(offset)
        length=packet[offset];offset+=1
        if length & 0xc0 == 0xc0:
            pointer=((length&0x3f)<<8)|packet[offset]
            if end is None:end=offset+1
            offset=pointer;continue
        if length==0:return '.'.join(labels)+'.', end or offset
        if length>63 or offset+length>len(packet):raise ValueError('Invalid DNS label')
        labels.append(packet[offset:offset+length].decode('utf-8'));offset+=length
    raise ValueError('DNS name is too long')


def records(packet):
    _,_,questions,answers,authority,additional=struct.unpack_from('!6H',packet)
    offset=12
    for _ in range(questions): _,offset=dns_name(packet,offset);offset+=4
    values=[]
    for _ in range(answers+authority+additional):
        name,offset=dns_name(packet,offset)
        kind,_,_,size=struct.unpack_from('!HHIH',packet,offset);offset+=10
        end=offset+size
        if end>len(packet):raise ValueError('Truncated DNS record')
        if kind==12: value,_=dns_name(packet,offset)
        elif kind==33:
            _,_,port=struct.unpack_from('!HHH',packet,offset)
            target,_=dns_name(packet,offset+6);value=(port,target)
        elif kind==1 and size==4:value=socket.inet_ntoa(packet[offset:end])
        elif kind==16:
            value=[];cursor=offset
            while cursor<end:
                count=packet[cursor];cursor+=1
                if cursor+count>end:raise ValueError('Invalid TXT record')
                value.append(packet[cursor:cursor+count].decode());cursor+=count
        else:value=None
        values.append((name.lower(),kind,value));offset=end
    return values


def probe(host, source):
    for address in (host,source):
        ip=ipaddress.ip_address(address)
        if ip.version!=4 or not ip.is_private or ip.is_loopback:raise ValueError('Use home LAN IPv4 addresses')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://{host}:18899/?action=getInfo',timeout=5) as response:info=json.load(response)
    assert info['status']==101
    service=info['deviceID'].lower()+'._spotify-connect._tcp.local.'
    query_name='_spotify-connect._tcp.local'
    query=struct.pack('!6H',secrets.randbelow(65535)+1,0,1,0,0,0)
    query+=b''.join(bytes([len(label)])+label.encode() for label in query_name.split('.'))+b'\0'+struct.pack('!HH',12,1)
    found={}; deadline=time.monotonic()+12
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind((source,0));sock.settimeout(1)
        sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(source))
        sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,255)
        while time.monotonic()<deadline:
            sock.sendto(query,('224.0.0.251',5353))
            try:data,peer=sock.recvfrom(65535)
            except socket.timeout:continue
            if peer[0]!=host:continue
            try:
                for name,kind,value in records(data):found[name,kind]=value
            except (ValueError,IndexError,struct.error,UnicodeError):continue
            target=found.get((service,33))
            if target and target[0]==18899 and found.get((target[1].lower(),1))==host:
                txt=found.get((service,16),[])
                if 'CPath=/' in txt and 'VERSION=1.0' in txt:
                    return {'http':101,'mdns':True,'host':host,'port':18899,'name':info['remoteName'],'pairing_requested':False}
    raise RuntimeError('Receiver HTTP works but LAN DNS-SD did not resolve')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default=deployment.device_host())
    parser.add_argument('--source',default='192.0.2.38')
    args=parser.parse_args()
    print(json.dumps(probe(args.host,args.source)))
