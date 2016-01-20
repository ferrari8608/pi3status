#!/usr/bin/env python

import argparse
import configparser
import fcntl
import ipaddress
import json
import os
import socket
import string
import struct
import subprocess
import sys
import threading
import time
import webcolors
from datetime import datetime
from glob import glob
from queue import Queue
from urllib.parse import urlsplit
try:
    from pynvml import *
except ImportError:
    pass

DEFAULT_SLEEP = 10  # Seconds
DEFAULT_STRFTIME = '%a %Y-%m-%d %H:%M'
DEFAULT_CONFIG_PATH = '~/.config/pi3status/config.ini'
DEFAULT_GPU_INDEX = 0
SIOCGIFADDR = 0x8915

class DiskSpace(object):
    def __init__(self, mount: str) -> None:
        self.stats = os.statvfs(mount)

    def _percentage(self, value: int, total: int) -> int:
        return int(value * 100 / total)

    @property
    def blocks_used(self) -> int:
        return self.stats.f_blocks - self.stats.f_bavail

    @property
    def free(self) -> str:
        return _hr_diskspace(self.stats.f_bavail * self.stats.f_frsize)

    @property
    def pfree(self) -> str:
        return self._percentage(self.stats.f_bavail, self.stats.f_blocks)

    @property
    def pused(self) -> str:
        return self._percentage(self.blocks_used, self.stats.f_blocks)

    @property
    def used(self) -> str:
        return _hr_diskspace(self.blocks_used * self.stats.f_frsize)

    @property
    def total(self) -> str:
        return _hr_diskspace(self.stats.f_blocks * self.stats.f_frsize)


class NvidiaStats(object):
    def __init__(self, gpuindex: int) -> None:
        self.handle = nvmlDeviceGetHandleByIndex(gpuindex)
        self.memoryunit = 'MiB'
        self._memoryinfo = None

    @property
    def memoryinfo(self) -> dict:
        if self._memoryinfo:
            return self._memoryinfo
        self._memoryinfo = nvmlDeviceGetMemoryInfo(self.handle)
        return self._memoryinfo

    @property
    def pfan(self) -> int:
        return nvmlDeviceGetFanSpeed(self.handle)

    @property
    def temperature(self) -> int:
        return nvmlDeviceGetTemperature(self.handle, NVML_TEMPERATURE_GPU)

    @property
    def free(self) -> str:
        return _hr_diskspace(self.memoryinfo.free, max_unit=self.memoryunit)

    @property
    def total(self) -> str:
        return _hr_diskspace(self.memoryinfo.total, max_unit=self.memoryunit)

    @property
    def used(self) -> str:
        return _hr_diskspace(self.memoryinfo.used, max_unit=self.memoryunit)

    @property
    def pfree(self) -> int:
        return int(self.memoryinfo.free / self.memoryinfo.total * 100)

    @property
    def pused(self) -> int:
        return int(self.memoryinfo.used / self.memoryinfo.total * 100)


class WorkerThread(threading.Thread):
    def __init__(self, args: dict, func_mapper: dict) -> None:
        super().__init__()
        self.args = args
        self.functions = func_mapper
        self.output = None

    def run(self) -> None:
        job = self.functions[self.args['function']]
        self.output = job(self.args)


def date_time(args: dict) -> dict:
    """Display the current date and/or time"""

    full_text = datetime.now().strftime(args['format'])
    return _assemble_json(args, full_text=full_text)

def disk_space(args: dict) -> dict:
    stats = DiskSpace(args['mount'])
    full_text = _parse_format_str(args['format'], stats)
    return _assemble_json(args, full_text=full_text)

def dns_lookup(args: dict) -> dict:
    """Use DNS lookup to determine network connectivity"""

    address = urlsplit(args['address']).netloc
    try:
        test_host, port = address.split()
    except ValueError:
        test_host = address
    try:
        socket.gethostbyname(test_host)
    except OSError:
        status = 'DOWN'
    else:
        status = 'UP'
    return _assemble_json(args, measurement=status)

def file_count(args: dict) -> dict:
    """Display number of files in given directory"""

    if 'pattern' in args:
        files = glob(os.path.join(args['directory'], args['pattern']))
    else:
        files = os.listdir(args['directory'])
    return _assemble_json(args, measurement=len(files))

def file_line_count(args: dict) -> dict:
    """Count the number of lines in the given file"""

    with open(args['path']) as counted_file:
        line_count = sum(1 for line in counted_file)
    return _assemble_json(args, measurement=line_count)

def system_load(args: dict) -> dict:
    """Display the system's load in one, five, and fifteen minute intervals"""

    with open('/proc/loadavg') as loadfile:
        loads = ' '.join(loadfile.read().strip().split()[:3])
    return _assemble_json(args, measurement=loads)

def output_line_count(args: dict) -> dict:
    """Check how many lines of output from the given command"""

    cmd = args['command'].strip().split()
    try:
        lines = sum(1 for line in subprocess.check_output(cmd).splitlines())
    except subprocess.CalledProcessError as err:
        sys.exit(err)
    return _assemble_json(args, measurement=lines)

def output_text(args: dict) -> dict:
    """Display output from the given command"""

    cmd = args['command'].strip().split()
    try:
        output = subprocess.check_output(cmd).strip()
    except subprocess.CalledProcessError as err:
        sys.exit(err)
    return _assemble_json(args, measurement=output)

def nvidia_stats(args: dict) -> dict:
    try:
        stats = NvidiaStats(args['gpu'])
    except KeyError:
        stats = NvidiaStats(DEFAULT_GPU_INDEX)
    full_text = _parse_format_str(args['format'], stats)
    return _assemble_json(args, full_text=full_text)

def uptime(args: dict) -> dict:
    """Display time elapsed since last system boot"""

    with open('/proc/uptime') as upfile:
        uptime_str = _hr_time(int(upfile.read().split('.')[0]))
    return _assemble_json(args, uptime_str)

def _assemble_json(args, measurement=None, full_text=None):
    if not full_text:
        full_text = args['format'].format(measurement)
    json_output = {
        'name':      args['function'],
        'instance':  args['instance'],
        'full_text': full_text,
        'separator': args['separator'],
    }
    color = args.get('color', None)
    if color:
        json_output['color'] = _get_color(color)
    return json_output

def _get_color(color: str):
    try:
        return webcolors.normalize_hex(color)
    except ValueError:
        pass
    try:
        return webcolors.name_to_hex(color)
    except ValueError:
        pass

def _get_config_sections(config):
    for section in (s for s in config.sections() if s != 'DEFAULT'):
        section_values = dict(config.items(section))
        section_values['instance'] = section
        section_values['separator'] = config.getboolean(section, 'separator')
        config.remove_section(section)
        yield section_values

def _get_ip_address(interface=None):  # -> ipaddress.IPv4Address or IPv6Address
    if not interface:
        return ipaddress.ip_address(socket.gethostbyname(socket.getfqdn()))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fd = sock.fileno()
    packed_s = struct.pack('256s', bytes(interface[:15].encode('utf8')))
    ip = socket.inet_ntoa(fcntl.ioctl(fd, SIOCGIFADDR, packed_s)[20:24])
    return ipaddress.ip_address(ip)

def _hr_diskspace(space_bytes, prefix='BINARY', max_unit=None):
    """Convert bytes to a human readable string"""

    (unit_text, divisor) = {
         'DECIMAL': (('B', 'kB', 'MB', 'GB', 'TB'), 1000),
         'BINARY':  (('B', 'KiB', 'MiB', 'GiB', 'TiB'), 1024),
    }.get(prefix.upper())
    previous = space_bytes
    for unit in unit_text:
        next = previous // divisor
        if not next or max_unit == unit:
           return '{value} {unit}'.format(value=previous, unit=unit)
        previous = next

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

def _init_json_output(json_seps):
    version = {'version': 1}
    version_str = json.dumps(version, separators=json_seps)
    return '\n'.join((version_str, '['))

def _parse_format_str(format_str, stats):
    measurements = dict()
    formatter = string.Formatter()
    for (_, field, _, _) in formatter.parse(format_str):
        try:
            measurements[field] = getattr(stats, field)
        except AttributeError:
            measurements[field] = ''
        except TypeError:
            continue
    return format_str.format(**measurements)

def _parse_config(config_path, parser=None):
    if not parser:
        parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path)
    return parser

def _wait_for_threads():
    while threading.activeCount() > 1:
        pass
    else:
        return

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--config', default=DEFAULT_CONFIG_PATH,
                        help='specify an alternate config file location')
    parser.add_argument('-s', '--sleep', type=float, default=DEFAULT_SLEEP,
                        help='time in seconds between refresh')
    return parser.parse_args()

def main():
    func_mapper = {
        'dns_lookup':        dns_lookup,
        'date_time':         date_time,
        'disk_space':        disk_space,
        'file_count':        file_count,
        'file_line_count':   file_line_count,
        'nvidia_stats':      nvidia_stats,
        'output_text':       output_text,
        'output_line_count': output_line_count,
        'system_load':       system_load,
        'uptime':            uptime,
    }
    json_seps = (',', ':')
    args = parse_arguments()
    try:
        nvmlInit()
    except NameError:
        pass
    config_path = os.path.expanduser(args.config)
    config = _parse_config(config_path)
    print(_init_json_output(json_seps), flush=True)

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
        _parse_config(config_path, config)
        for worker in workers:
            worker.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('\n')
