#!/usr/bin/env python

import alsaaudio
import collections
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from argparse import ArgumentParser
from configparser import ConfigParser
from datetime import datetime
from glob import glob
from queue import Queue

try:
    from pynvml import *
except ImportError:
    _NVIDIA_SUPPORT = False
else:
    _NVIDIA_SUPPORT = True

# Set default global values
_DEF_SLEEP = 10  # Seconds
_DEF_STRFTIME = '%a %Y-%m-%d %H:%M'
_DEF_CONFIG_PATH = os.path.expanduser('~/.config/pi3status/config.ini')
_FUNC_MAP = dict()  # Initialize
_PACMAN_CACHE_DIR = '/var/cache/pacman/pkg'
COLORS = {
    'CYAN':   '#00FFFF',
    'GREEN':  '#00FF00',
    'RED':    '#FF0000',
    'WHITE':  '#FFFFFF',
    'YELLOW': '#FFFF00',
}

#class Volume(WorkerThread):
#    """Check the volume level percentage"""
#
#    def run(self):
#        try:
#            mixer = alsaaudio.Mixer()#cardindex=1)
#            volumes = mixer.getvolume()
#        except alsaaudio.ALSAAudioError:
#            percentage = 'ERROR'
#            instance = None
#            color = COLORS['RED']
#        else:
#            percentage = str(int(sum(volumes) / len(volumes)))
#            stats = (mixer.cardname(), mixer.mixer(), str(mixer.mixerid()))
#            instance = '.'.join(stats)
#            color = COLORS['WHITE']
#        self.output = {
#            'name':      'volume',
#            'instance':  instance,
#            'full_text': ' ♫ {}% '.format(percentage),
#            'separator': False,
#            'color':     color,
#        }
#
#
#class WANConnection(threading.Thread):
#    """Open a test URL and output the status of the request."""
#
#    def __init__(self, testaddr):
#        threading.Thread.__init__(self)
#        self.testaddr = testaddr
#        self.output = None
#
#    def run(self):
#        try:
#            dns_lookup_test = socket.gethostbyname(self.testaddr)
#        except OSError:
#            status = 'DOWN'
#            color = COLORS['RED']
#        else:
#            status = 'UP'
#            color = COLORS['GREEN']
#        self.output = {
#            'name':      'wan_connection',
#            'full_text': ' WAN: {} ' .format(status),
#            'color':     color,
#            'separator': False,
#        }
#
#class GPUStats(threading.Thread):
#    """Check GPU temperature and fan speed"""
#
#    def __init__(self, gpuindex=0):
#        threading.Thread.__init__(self)
#        self.gpuindex = gpuindex
#        self.output = None
#
#    def run(self):
#        handle = nvmlDeviceGetHandleByIndex(self.gpuindex)
#        temperature = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
#        fan_speed = nvmlDeviceGetFanSpeed(handle)
#        self.output = {
#            'name':      'gpu_stats',
#            'full_text': ' GPU: {}°C {}%'.format(temperature, fan_speed),
#            'separator': False,
#        }

class WorkerThread(threading.Thread):
    def __init__(self, args, func_mapper):
        super().__init__()
        self.args = args
        self.functions = func_mapper
        self.output = None

    def run(self):
        job = self.functions[self.args['function']]
        self.output = job(self.args)


def disk_free(args):
    stat = os.statvfs(args['mount'])
    if args['percentage']:
        free = (stat.f_bavail * 100) / stat.f_blocks
    else:
        free = _hr_diskspace(stat.f_bavail * stat.f_frsize)
    return {
        'name':      args['function'],
        'instance':  args['mount'],
        'full_text': args['format'].format(mount=args['mount'], free=free),
        'separator': False,
    }

def disk_used(args):
    stat = os.statvfs(args['mount'])
    blocks_used = (stat.f_blocks - stat.f_bavail)
    if args.getboolean('percentage'):
        used = (blocks_used * 100) / stat.f_blocks
    else:
        used = _hr_diskspace(blocks_used * stat.f_frsize)
    return {
        'name':      args['function'],
        'instance':  args['mount'],
        'full_text': args['format'].format(mount=args['mount'], used=used),
        'separator': False,
    }

def load(args):
    with open('/proc/loadavg') as loadfile:
        load_str = ' '.join(loadfile.read().split()[:3])

    return {
        'name':      args['function'],
        'full_text': args['format'].format(load_str),
        'separator': args['separator'],
    }

def date_time(args):
    return {
        'name':      args['function'],
        'full_text': datetime.now().strftime(args['format']),
        'separator': args['separator'],
    }

def uptime(args):
    with open('/proc/uptime') as upfile:
        uptime_str = _hr_time(int(upfile.read().split('.')[0]))

    return {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': args['format'].format(uptime_str),
        'separator': args['separator'],
    }

def pacman_updates(args):
    """Check how many system updates are available"""

    try:
        packages = subprocess.check_output('checkupdates').splitlines()
    except subprocess.CalledProcessError as err:
        print(err)
        sys.exit(1)

    return {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': args['format'].format(len(packages)),
        'separator': args['separator'],
    }


def file_count(args):
    if 'pattern' in args:
        files = glob(os.path.join(args['directory'], args['pattern']))
    else:
        files = os.listdir(args['directory'])

    return {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': args['format'].format(len(files)),
        'separator': args['separator'],
    }

def _hr_diskspace(bytes):
    """Convert bytes to a human readable string"""

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
    """Convert time in seconds to a human readable string"""

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

def _parse_config(config_path, parser=None):
    config_path = os.path.expandvars(os.path.expanduser(config_path))
    if not parser:
        parser = ConfigParser(interpolation=None)
    with open(config_path) as config:
        parser.read_file(config)
    return parser

def _get_config_sections(config):
    for section in config.sections():
        if section == 'DEFAULT':
            continue
        section_values = dict(config.items(section))
        section_values['instance'] = section
        config.remove_section(section)
        yield section_values

def _init_json_output(json_seps):
    version = {"version": 1}
    version_str = json.dumps(version, separators=json_seps)
    print(version_str, '[', sep='\n', flush=True)

def _wait_for_threads():
    while threading.activeCount() > 1:
        pass
    else:
        return

def parse_arguments():
    global _DEF_CONFIG_PATH
    global _DEF_SLEEP
    parser = ArgumentParser()
    parser.add_argument('-f', '--config', default=_DEF_CONFIG_PATH,
                        help='specify an alternate config file location')
    parser.add_argument('-s', '--sleep', type=float, default=_DEF_SLEEP,
                        help='time in seconds between refresh')
    return parser.parse_args()

def main():
    func_mapper = {
        'date_time':      date_time,
        'disk_free':      disk_free,
        'disk_used':      disk_used,
        'file_count':     file_count,
        'load':           load,
        'pacman_updates': pacman_updates,
        'uptime':         uptime,
    }
    json_seps = (',', ':')

    args = parse_arguments()
    if _NVIDIA_SUPPORT:
        nvmlInit()
    config = _parse_config(args.config)
    _init_json_output(json_seps)

    # Initialize and first run the workers
    workers = [WorkerThread(items, func_mapper) 
               for items in _get_config_sections(config)]
    for worker in workers:
        worker.start()

    while True:
        # Dump JSON to stdout
        _wait_for_threads()
        bar_data = [worker.output for worker in workers]
        json_data = json.dumps(bar_data, separators=json_seps)
        print(json_data, ',', sep='\n', flush=True)

        # Sleep, reconfigure, and run the threads
        time.sleep(args.sleep)
        _parse_config(args.config, config)
        for worker in workers:
            worker.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('\n')
