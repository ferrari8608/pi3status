#!/usr/bin/env python

import alsaaudio
import collections
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

_DEF_REFRESH = 10  # Seconds
_DEF_STRFTIME = '%a %Y-%m-%d %H:%M'
_DEF_TEST_ADDRESS = 'https://www.google.com'
_DEF_TIMEOUT = 0.1  # Seconds

COLORS = {
    'CYAN':   '#00FFFF',
    'RED':    '#FF0000',
    'WHITE':  '#FFFFFF',
    'YELLOW': '#FFFF00',
}

def _hr_diskspace(bytes):
    kbytes = bytes // 1024
    if not kbytes:
        return '{} B'.format(bytes)
    mbytes = kbytes // 1024
    if not mbytes:
        return '{} KB'.format(kbytes)
    gbytes = mbytes // 1024
    if not gbytes:
        return '{} MB'.format(mbytes)
    tbytes = gbytes // 1024
    if not tbytes:
        return '{} GB'.format(gbytes)
    else:
        return '{} TB'.format(tbytes)

def _hr_time(seconds):
    minutes = seconds // 60
    if not minutes:
        return '{}s'.format(seconds)
    hours = minutes // 60
    if not hours:
        seconds -= minutes * 60
        return '{}m {}s'.format(minutes, seconds)
    days = hours // 24
    if not days:
        minutes -= hours * 60
        return '{}h {}m'.format(hours, minutes)
    years = days // 365
    if not years:
        hours -= days * 24
        return '{}d {}h'.format(days, hours)
    else:
        days -= years * 365
        return '{}y {}d'.format(years, days)

def volume():
    try:
        mixer = alsaaudio.Mixer()#cardindex=1)
        volumes = mixer.getvolume()
    except alsaaudio.ALSAAudioError:
        percentage = 'ERROR'
        instance = None
        color = COLORS['RED']
    else:
        percentage = str(int(sum(volumes) / len(volumes)))
        stats = (mixer.cardname(), mixer.mixer(), str(mixer.mixerid()))
        instance = '.'.join(stats)
        color = COLORS['WHITE']
    return {
        'name':      'volume',
        'instance':  instance,
        'full_text': ' ♫ {}% '.format(percentage),
        'separator': False,
        'color':     color,
    }

def uptime():
    with open('/proc/uptime') as upfile:
        uptime_str = _hr_time(int(upfile.read().split('.')[0]))
    return {
        'name':      'uptime',
        'full_text': ' UPTIME: {} '.format(uptime_str),
        'separator':  False,
    }

def load():
    with open('/proc/loadavg') as loadfile:
        load_str = ' '.join(loadfile.read().split()[:3])
    return {
        'name':      'load',
        'full_text': ' LOAD: {} '.format(load_str),
        'separator': False,
    }

def diskfree(mount):
    stat = os.statvfs(mount)
    free = stat.f_bavail * stat.f_frsize
    return {
        'name':      'disk_info',
        'instance':  mount,
        'full_text': ' {}: {} '.format(mount, _hr_diskspace(free)),
        'separator': False,
    }

def cpu():
    with open('/proc/stat') as statfile:
        for line in statfile.readlines():
            stats = ProcCPUStats(*line.split())
            break

def current_time(timeform=_DEF_STRFTIME):
    timestr = datetime.now().strftime(timeform)
    return {
        'name':      'time',
        'full_text': ' {} '.format(timestr),
        'separator': False,
        'color':     '#00FFFF',
    }

def wan_connection(testaddr=_DEF_TEST_ADDRESS):
    try:
        urllib.request.urlopen(testaddr, timeout=_DEF_TIMEOUT)
    except urllib.request.URLError:
        status = 'DOWN'
        color = COLORS['RED']
    except:
        status = 'ERROR'
        color =  COLORS['YELLOW']
    else:
        status = 'UP'
        color = None
    values = {
        'name':      'wan_connection',
        'full_text': ' WAN: {} ' .format(status),
        'separator': False,
    }
    if color:
        values['color'] = color
    return values

def main():
    json_seps = (',', ':')
    version = {"version": 1}
    version_str = json.dumps(version, separators=json_seps)
    print(version_str, '[', sep='\n', flush=True)

    while True:
        bar_data = [
            wan_connection(),
            diskfree('/'),
            diskfree('/home'),
            load(),
            uptime(),
            volume(),
            current_time(),
        ]
        json_data = json.dumps(bar_data, separators=json_seps)
        print(json_data, flush=True)
        time.sleep(_DEF_REFRESH)
        print('\n,', end='', flush=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('\n')
