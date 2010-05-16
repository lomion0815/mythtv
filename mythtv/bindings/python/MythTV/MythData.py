# -*- coding: utf-8 -*-

"""
Provides data access classes for accessing and managing MythTV data
"""

from MythStatic import *
from MythBase import *

import re
import sys
import socket
import os
import xml.etree.cElementTree as etree
from time import mktime, strftime, strptime, altzone
from datetime import date, time, datetime, timedelta
from socket import gethostbyaddr, gethostname

#### FILE ACCESS ####

def findfile(filename, sgroup, db=None):
    """
    findfile(filename, sgroup, db=None) -> StorageGroup object

    Will search through all matching storage groups, searching for file.
    Returns matching storage group upon success.
    """
    db = DBCache(db)
    for sg in db.getStorageGroup(groupname=sgroup):
        # search given group
        if not sg.local:
            continue
        if os.access(sg.dirname+filename, os.F_OK):
            return sg
    for sg in db.getStorageGroup():
        # not found, search all other groups
        if not sg.local:
            continue
        if os.access(sg.dirname+filename, os.F_OK):
            return sg
    return None

def ftopen(file, mode, forceremote=False, nooverwrite=False, db=None, \
                       chanid=None, starttime=None):
    """
    ftopen(file, mode, forceremote=False, nooverwrite=False, db=None)
                                        -> FileTransfer object
                                        -> file object
    Method will attempt to open file locally, falling back to remote access
            over mythprotocol if necessary.
    'forceremote' will force a FileTransfer object if possible.
    'file' takes a standard MythURI:
                myth://<group>@<host>:<port>/<path>
    'mode' takes a 'r' or 'w'
    'nooverwrite' will refuse to open a file writable, if a local file is found.
    """
    db = DBCache(db)
    log = MythLog('Python File Transfer', db=db)
    reuri = re.compile(\
        'myth://((?P<group>.*)@)?(?P<host>[a-zA-Z0-9_\.]*)(:[0-9]*)?/(?P<file>.*)')
    reip = re.compile('(?:\d{1,3}\.){3}\d{1,3}')

    if mode not in ('r','w'):
        raise TypeError("File I/O must be of type 'r' or 'w'")

    # process URI (myth://<group>@<host>[:<port>]/<path/to/file>)
    match = reuri.match(file)
    if match is None:
        raise MythError('Invalid FileTransfer input string: '+file)
    host = match.group('host')
    filename = match.group('file')
    sgroup = match.group('group')
    if sgroup is None:
        sgroup = 'Default'

    # get full system name
    if reip.match(host):
        c = db.cursor(log)
        if c.execute("""SELECT hostname FROM settings
                        WHERE value='BackendServerIP'
                        AND data=%s""", host) == 0:
            c.close()
            raise MythDBError(MythError.DB_SETTING, \
                              'BackendServerIP', backend)
        host = c.fetchone()[0]
        c.close()

    # user forced to remote access
    if forceremote:
        if (mode == 'w') and (filename.find('/') != -1):
            raise MythFileError(MythError.FILE_FAILED_WRITE, file, 
                                'attempting remote write outside base path')
        if nooverwrite and FileOps(host, db=db).fileExists(filename, sgroup):
            raise MythFileError(MythError.FILE_FAILED_WRITE, file, 
                                'refusing to overwrite existing file')
        return FileTransfer(host, filename, sgroup, mode, db, \
                                  chanid, starttime)

    if mode == 'w':
        # check for pre-existing file
        path = FileOps(host, db=db).fileExists(filename, sgroup)
        sgs = db.getStorageGroup(groupname=sgroup)
        if path is not None:
            if nooverwrite:
                raise MythFileError(MythError.FILE_FAILED_WRITE, file, 
                                'refusing to overwrite existing file')
            for sg in sgs:
                if sg.dirname in path:
                    if sg.local:
                        return open(sg.dirname+filename, mode)
                    else:
                        return FileTransfer(host, filename, sgroup, 'w', \
                                    db, chanid, starttime)

        # prefer local storage for new files
        for i in reversed(xrange(len(sgs))):
            if not sgs[i].local:
                sgs.pop(i)
            else:
                st = os.statvfs(sgs[i].dirname)
                sgs[i].free = st[0]*st[3]
        if len(sgs) > 0:
            # choose path with most free space
            sg = sorted(sgs, key=lambda sg: sg.free, reverse=True)[0]
            # create folder if it does not exist
            if filename.find('/') != -1:
                path = sg.dirname+filename.rsplit('/',1)[0]
                if not os.access(path, os.F_OK):
                    os.makedirs(path)
            log(log.FILE, 'Opening local file (w)', sg.dirname+filename)
            return open(sg.dirname+filename, mode)

        # fallback to remote write
        else:
            if filename.find('/') != -1:
                raise MythFileError(MythError.FILE_FAILED_WRITE, file, 
                                'attempting remote write outside base path')
            return FileTransfer(host, filename, sgroup, 'w', db, \
                                      chanid, starttime)
    else:
        # search for file in local directories
        sg = findfile(filename, sgroup, db)
        if sg is not None:
            # file found, open local
            log(log.FILE, 'Opening local file (r)',
                           sg.dirname+filename)
            return open(sg.dirname+filename, mode)
        else:
        # file not found, open remote
            return FileTransfer(host, filename, sgroup, mode, db, \
                                  chanid=None, starttime=None)

class FileTransfer( BEEvent ):
    """
    A connection to mythbackend intended for file transfers.
    Emulates the primary functionality of the local 'file' object.
    """
    logmodule = 'Python FileTransfer'

    class BETransConn( BEConnection ):
        def __init__(self, host, port, filename, sgroup, mode):
            self.filename = filename
            self.sgroup = sgroup
            self.mode = mode
            BEConnection.__init__(self, host, port)

        def announce(self):
            if self.mode == 'r':
                write = False
            elif self.mode == 'w':
                write = True

            res = self.backendCommand('ANN FileTransfer %s %d %d %s' \
                      % (self.localname, write, False, 
                         BACKEND_SEP.join(
                                ['-1', self.filename, self.sgroup])))
            if res.split(BACKEND_SEP)[0] != 'OK':
                raise MythBEError(MythError.PROTO_ANNOUNCE,
                                  self.host, self.port, res)
            else:
                sp = res.split(BACKEND_SEP)
                self._sockno = int(sp[1])
                self._size = sp[2:]

        def __del__(self):
            self.socket.shutdown(1)
            self.socket.close()

    def __repr__(self):
        return "<open file 'myth://%s:%s/%s', mode '%s' at %s>" % \
                          (self.sgroup, self.host, self.filename, \
                                self.mode, hex(id(self)))

    def _listhandlers(self):
        if self.chanid and self.starttime:
            self.re_update = re.compile(\
                    BACKEND_SEP.join(['BACKEND_MESSAGE',
                             'UPDATE_FILE_SIZE %s %s (?P<size>[0-9]*)' %\
                            (self.chanid, \
                             self.starttime.strftime('%Y-%m-%dT%H-%M-%S')),
                             'empty']))
            return [self.updatesize]
        return []

    def updatesize(self, event):
        if event is None:
            return self.re_update
        match = self.re_update(event)
        self._size = match.group('size')

    def __init__(self, host, filename, sgroup, mode, db=None, \
                       chanid=None, starttime=None):
        self.filename = filename
        self.sgroup = sgroup
        self.mode = mode
        self.chanid = chanid
        self.starttime = starttime

        # open control socket
        BEEvent.__init__(self, host, True, db=db)
        # open transfer socket
        self.ftsock = self.BETransConn(self.host, self.port, self.filename,
                                       self.sgroup, self.mode)
        self.open = True

        self._sockno = self.ftsock._sockno
        self._size = self.joinInt(*self.ftsock._size)
        self._pos = 0
        self._tsize = 2**15
        self._tmax = 2**17
        self._count = 0
        self._step = 2**12

    def __del__(self):
        self.backendCommand('QUERY_FILETRANSFER '+BACKEND_SEP.join(
                                        [str(self._sockno), 'JOIN']))
        del self.ftsock
        self.open = False

    def tell(self):
        """FileTransfer.tell() -> current offset in file"""
        return self._pos

    def close(self):
        """FileTransfer.close() -> None"""
        self.__del__()

    def rewind(self):
        """FileTransfer.rewind() -> None"""
        self.seek(0)

    def read(self, size):
        """
        FileTransfer.read(size) -> string of <size> characters
            Requests over 128KB will be buffered internally.
        """

        # some sanity checking
        if self.mode != 'r':
            raise MythFileError('attempting to read from a write-only socket')
        if size == 0:
            return ''
        if self._pos + size > self._size:
            size = self._size - self._pos

        buff = ''
        while len(buff) < size:
            ct = size - len(buff)
            if ct > self._tsize:
                # drop size and bump counter if over limit
                self._count += 1
                ct = self._tsize

            # request transfer
            res = self.backendCommand('QUERY_FILETRANSFER '\
                        +BACKEND_SEP.join(
                                [str(self._sockno),
                                 'REQUEST_BLOCK',
                                 str(ct)]))

            if int(res) == ct:
                if (self._count >= 5) and (self._tsize < self._tmax):
                    # multiple successful transfers, bump transfer limit
                    self._count = 0
                    self._tsize += self._step

            else:
                if int(res) == -1:
                    # complete failure, hard reset position and retry
                    self._count = 0
                    self.seek(self._pos)
                    continue

                # partial failure, reset counter and drop transfer limit
                ct = int(res)
                self._count = 0
                self._tsize -= 2*self._step
                if self._tsize < self._step:
                    self._tsize = self._step

            # append data and move position
            buff += self.ftsock._recv(ct)
            self._pos += ct
        return buff

    def write(self, data):
        """
        FileTransfer.write(data) -> None
            Requests over 128KB will be buffered internally
        """
        if self.mode != 'w':
            raise MythFileError('attempting to write to a read-only socket')
        while len(data) > 0:
            size = len(data)
            # check size for buffering
            if size > self._tsize:
                size = self._tsize
                buff = data[:size]
                data = data[size:]
            else:
                buff = data
                data = ''
            # push data to server
            self.pos += int(self.ftsock._send(buff, False))
            # inform server of new data
            self.backendCommand('QUERY_FILETRANSFER '\
                    +BACKEND_SEP.join(\
                            [str(self._sockno),
                             'WRITE_BLOCK',
                             str(size)]))
        return

    def seek(self, offset, whence=0):
        """
        FileTransfer.seek(offset, whence=0) -> None
            Seek 'offset' number of bytes
            whence == 0 - from start of file
                      1 - from current position
                      2 - from end of file
        """
        if whence == 0:
            if offset < 0:
                offset = 0
            elif offset > self._size:
                offset = self._size
        elif whence == 1:
            if offset + self._pos < 0:
                offset = -self._pos
            elif offset + self._pos > self._size:
                offset = self._size - self._pos
        elif whence == 2:
            if offset > 0:
                offset = 0
            elif offset < -self._size:
                offset = -self._size
            whence = 0
            offset = self._size+offset

        curhigh,curlow = self.splitInt(self._pos)
        offhigh,offlow = self.splitInt(offset)

        res = self.backendCommand('QUERY_FILETRANSFER '\
                +BACKEND_SEP.join(
                        [str(self._sockno),'SEEK',
                         str(offhigh),str(offlow),
                         str(whence),
                         str(curhigh),str(curlow)])\
                 ).split(BACKEND_SEP)
        self._pos = self.joinInt(*res)
        
class FileOps( BEEvent ):
    __doc__ = BEEvent.__doc__+"""
        getRecording()      - return a Program object for a recording
        deleteRecording()   - notify the backend to delete a recording
        forgetRecording()   - allow a recording to re-record
        deleteFile()        - notify the backend to delete a file
                              in a storage group
        getHash()           - return the hash of a file in a storage group
        reschedule()        - trigger a run of the scheduler
    """
    logmodule = 'Python Backend FileOps'

    def getRecording(self, chanid, starttime):
        """FileOps.getRecording(chanid, starttime) -> Program object"""
        res = self.backendCommand('QUERY_RECORDING TIMESLOT %d %d' \
                        % (chanid, starttime)).split(BACKEND_SEP)
        if res[0] == 'ERROR':
            return None
        else:
            return Program(res[1:], db=self.db)
    
    def deleteRecording(self, program, force=False):
        """
        FileOps.deleteRecording(program, force=False) -> retcode
            'force' will force a delete even if the file cannot be found
            retcode will be -1 on success, -2 on failure
        """
        command = 'DELETE_RECORDING'
        if force:
            command = 'FORCE_DELETE_RECORDING'
        return self.backendCommand(BACKEND_SEP.join(\
                    [command,program.toString()]))

    def forgetRecording(self, program):
        """FileOps.forgetRecording(program) -> None"""
        self.backendCommand(BACKEND_SEP.join(['FORGET_RECORDING',
                    program.toString()]))

    def deleteFile(self, file, sgroup):
        """FileOps.deleteFile(file, storagegroup) -> retcode"""
        return self.backendCommand(BACKEND_SEP.join(\
                    ['DELETE_FILE',file,sgroup]))

    def getHash(self, file, sgroup):
        """FileOps.getHash(file, storagegroup) -> hash string"""
        return self.backendCommand(BACKEND_SEP.join((\
                    'QUERY_FILE_HASH',file, sgroup)))

    def reschedule(self, recordid=-1):
        """FileOps.reschedule() -> None"""
        self.backendCommand('RESCHEDULE_RECORDINGS '+str(recordid))

    def fileExists(self, file, sgroup='Default'):
        """FileOps.fileExists() -> file path"""
        res = self.backendCommand(BACKEND_SEP.join((\
                    'QUERY_FILE_EXISTS',file,sgroup))).split(BACKEND_SEP)
        if int(res[0]) == 0:
            return None
        else:
            return res[1]

class Record( DBDataWrite, RECTYPE ):
    """
    Record(id=None, db=None, raw=None) -> Record object
    """

    _table = 'record'
    _where = 'recordid=%s'
    _setwheredat = 'self.recordid,'
    _defaults = {'recordid':None,    'type':RECTYPE.kAllRecord,
                 'title':u'Unknown', 'subtitle':'',      'description':'',
                 'category':'',      'station':'',       'seriesid':'',
                 'search':0,         'last_record':datetime(1900,1,1),
                 'next_record':datetime(1900,1,1),
                 'last_delete':datetime(1900,1,1)}
    _logmodule = 'Python Record'

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized Record Rule at %s>" % hex(id(self))
        return u"<Record Rule '%s', Type %d at %s>" \
                                    % (self.title, self.type, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, id=None, db=None, raw=None):
        DBDataWrite.__init__(self, (id,), db, raw)

    def create(self, data=None):
        """Record.create(data=None) -> Record object"""
        self._wheredat = (DBDataWrite.create(self, data),)
        self._pull()
        FileOps(db=self._db).reschedule(self.recordid)
        return self

    def update(self, *args, **keywords):
        DBDataWrite.update(*args, **keywords)
        FileOps(db=self._db).reschedule(self.recordid)

class FreeSpace( DictData ):
    """Represents a FreeSpace entry."""
    _field_order = [ 'host',         'path',     'islocal',
                    'disknumber',   'sgroupid', 'blocksize',
                    'ts_high',      'ts_low',   'us_high',
                    'us_low']
    _field_type = [3, 3, 2, 0, 0, 0, 0, 0, 0, 0]
    def __str__(self):
        return "<FreeSpace '%s@%s' at %s>"\
                    % (self.path, self.host, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, raw):
        DictData.__init__(self, raw)
        self.totalspace = self.joinInt(self.ts_high, self.ts_low)
        self.usedspace = self.joinInt(self.us_high, self.us_low)
        self.freespace = self.totalspace - self.usedspace


#### RECORDING ACCESS ####

class Program( DictData, RECSTATUS ):
    """Represents a program with all detail returned by the backend."""

    _field_order = [ 'title',        'subtitle',     'description',
                     'category',     'chanid',       'channum',
                     'callsign',     'channame',     'filename',
                     'filesize',     'starttime',    'endtime',      
                     'findid',       'hostname',     'sourceid',
                     'cardid',       'inputid',      'recpriority',
                     'recstatus',    'recordid',     'rectype',
                     'dupin',        'dupmethod',    'recstartts',
                     'recendts',     'programflags', 'recgroup',     
                     'outputfilters','seriesid',     'programid',
                     'lastmodified', 'stars',        'airdate',
                     'playgroup',    'recpriority2', 'parentid',
                     'storagegroup', 'audio_props',  'video_props',
                     'subtitle_type','year']
    _field_type = [  3,      3,      3,
                     3,      0,      3,
                     3,      3,      3,
                     0,      4,      4,                
                     0,      3,      0,
                     0,      0,      0,
                     0,      0,      3,
                     0,      0,      4,
                     4,      3,      3,
                     3,      3,      3,
                     3,      1,      3,
                     3,      0,      3,
                     3,      0,      0,
                     0,      0]
    def __str__(self):
        return u"<Program '%s','%s' at %s>" % (self.title,
                 self.starttime.strftime('%Y-%m-%d %H:%M:%S'), hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, raw=None, db=None, etree=None):
        if raw:
            DictData.__init__(self, raw)
        elif etree:
            xmldat = etree.attrib
            xmldat.update(etree.find('Channel').attrib)
            if etree.find('Recording'):
                xmldat.update(etree.find('Recording').attrib)

            dat = {}
            if etree.text:
                dat['description'] = etree.text.strip()
            for key in ('title','subTitle','seriesId','programId','airdate',
                    'category','hostname','chanNum','callSign','playGroup',
                    'recGroup','rectype','programFlags','chanId','recStatus',
                    'commFree','stars','filesize'):
                if key in xmldat:
                    dat[key.lower()] = xmldat[key]
            for key in ('startTime','endTime','lastModified',
                                    'recStartTs','recEndTs'):
                if key in xmldat:
                    dat[key.lower()] = str(int(mktime(strptime(
                                        xmldat[key], '%Y-%m-%dT%H:%M:%S'))))

            raw = []
            defs = (0,0,0,'',0)
            for i in xrange(len(self._field_order)):
                if self._field_order[i] in dat:
                    raw.append(dat[self._field_order[i]])
                else:
                    raw.append(defs[self._field_type[i]])
            DictData.__init__(self, raw)
        else:
            raise InputError("Either 'raw' or 'etree' must be provided")
        self._db = DBCache(db)

    def toString(self):
        """
        Program.toString() -> string representation
                    for use with backend protocol commands
        """
        return BACKEND_SEP.join(self._deprocess())

    def delete(self, force=False, rerecord=False):
        """
        Program.delete(force=False, rerecord=False) -> retcode
                Informs backend to delete recording and all relevent data.
                'force' forces a delete if the file cannot be found.
                'rerecord' sets the file as recordable in oldrecorded
        """
        be = FileOps(db=self._db)
        res = int(be.deleteRecording(self, force=force))
        if res < -1:
            raise MythBEError('Failed to delete file')
        if rerecord:
            be.forgetRecording(self)
        return res

    def getRecorded(self):
        """Program.getRecorded() -> Recorded object"""
        return Recorded((self.chanid,self.recstartts), db=self._db)

    def open(self, type='r'):
        """Program.open(type='r') -> file or FileTransfer object"""
        if type != 'r':
            raise MythFileError(MythError.FILE_FAILED_WRITE, self.filename, 
                            'Program () objects cannot be opened for writing')
        return ftopen(self.filename, 'r', chanid=self.chanid, \
                      starttime=self.starttime)

    def record(self, type=Record.kSingleRecord):
        if datetime.now() > self.endtime:
            raise MythError('Cannot create recording rule for past recording.')
        rec = Record(db=self._db)
        for key in ('chanid','title','subtitle','description','category',
                    'seriesid','programid'):
            rec[key] = self[key]

        rec.startdate = self.starttime.date()
        rec.starttime = self.starttime-datetime.combine(rec.startdate, time())
        rec.enddate = self.endtime.date()
        rec.endtime = self.endtime-datetime.combine(rec.enddate, time())

        rec.station = self.callsign
        rec.type = type
        return rec.create()

    def formatPath(self, path, replace=None):
        """
        Program.formatPath(path, replace=None) -> formatted path string
                'path' string is formatted as per mythrename.pl syntax
        """
        for (tag, data) in (('T','title'), ('S','subtitle'),
                            ('R','description'), ('C','category'),
                            ('U','recgroup'), ('hn','hostname'),
                            ('c','chanid') ):
            tmp = unicode(self[data]).replace('/','-')
            path = path.replace('%'+tag, tmp)
        for (data, pre) in (   ('recstartts','%'), ('recendts','%e'),
                               ('starttime','%p'),('endtime','%pe') ):
            for (tag, format) in (('y','%y'),('Y','%Y'),('n','%m'),('m','%m'),
                                  ('j','%d'),('d','%d'),('g','%I'),('G','%H'),
                                  ('h','%I'),('H','%H'),('i','%M'),('s','%S'),
                                  ('a','%p'),('A','%p') ):
                path = path.replace(pre+tag, self[data].strftime(format))
        airdate = date(*[int(a) for a in self.airdate.split('-')])
        for (tag, format) in (('y','%y'),('Y','%Y'),('n','%m'),('m','%m'),
                              ('j','%d'),('d','%d')):
            path = path.replace('%o'+tag, airdate.strftime(format))
        path = path.replace('%-','-')
        path = path.replace('%%','%')
        path += '.'+self.filename.split('.')[-1]

        # clean up for windows
        if replace is not None:
            for char in ('\\',':','*','?','"','<','>','|'):
                path = path.replace(char, replace)
        return path

    def formatJob(self, cmd):
        """
        Program.formatPath(cmd) -> formatted command string
                'cmd' string is formatted as per MythJobQueue syntax
        """
        for tag in ('chanid','title','subtitle','description','hostname',
                    'category','recgroup','playgroup','parentid','findid',
                    'recstatus','rectype'):
            cmd = cmd.replace('%%%s%%' % tag.upper(), str(self[tag]))
        for (tag, data) in (('STARTTIME','recstartts'),('ENDTIME','recendts'),
                            ('PROGSTART','starttime'),('PROGEND','endtime')):
            cmd = cmd.replace('%%%s%%' % tag, \
                        self[data].strftime('%Y%m%d%H%M%S'))
            cmd = cmd.replace('%%%sISO%%' % tag, \
                        self[data].isoformat())
            cmd = cmd.replace('%%%sISOUTC%%' % tag, \
                        (self[data]+timedelta(0,altzone)).isoformat())
        cmd = cmd.replace('%VERBOSELEVEL%', MythLog._parselevel())
        cmd = cmd.replace('%RECID%', str(self.recordid))

        path = FileOps(self.hostname, db=self._db).fileExists(\
                        self.filename.rsplit('/',1)[1], self.storagegroup)
        cmd = cmd.replace('%DIR%', path.rsplit('/',1)[0])
        cmd = cmd.replace('%FILE%',path.rsplit('/',1)[1])
        cmd = cmd.replace('%REACTIVATE%', str(OldRecorded(\
                    (self.chanid, self.recstartts),db=self._db).reactivate))
        return cmd


class Recorded( DBDataWrite ):
    """
    Recorded(data=None, db=None, raw=None) -> Recorded object
            'data' is a tuple containing (chanid, storagegroup)
    """
    _table = 'recorded'
    _where = 'chanid=%s AND starttime=%s'
    _setwheredat = 'self.chanid,self.starttime'
    _defaults = {'title':u'Unknown', 'subtitle':'',          'description':'',
                 'category':'',      'hostname':'',          'bookmark':0,
                 'editing':0,        'cutlist':0,            'autoexpire':0,
                 'commflagged':0,    'recgroup':'Default',   'seriesid':'',
                 'programid':'',     'lastmodified':'CURRENT_TIMESTAMP',
                 'filesize':0,       'stars':0,              'previouslyshown':0,
                 'preserve':0,       'bookmarkupdate':0,
                 'findid':0,         'deletepending':0,      'transcoder':0,
                 'timestretch':1,    'recpriority':0,        'playgroup':'Default',
                 'profile':'No',     'duplicate':1,          'transcoded':0,
                 'watched':0,        'storagegroup':'Default'}
    _logmodule = 'Python Recorded'

    class _Cast( DBDataCRef ):
        _table = ['recordedcredits','people']
        _ref = ['chanid','starttime']
        _cref = ['person']

    class _Seek( DBDataRef, MARKUP ):
        _table = 'recordedseek'
        _ref = ['chanid','starttime']

    class _Markup( DBDataRef, MARKUP ):
        _table = 'recordedmarkup'
        _ref = ['chanid','starttime']
        
    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized Recorded at %s>" % hex(id(self))
        return u"<Recorded '%s','%s' at %s>" % (self.title,
                self.starttime.strftime('%Y-%m-%d %H:%M:%S'), hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, data=None, db=None, raw=None):
        DBDataWrite.__init__(self, data, db, raw)
        if (data is not None) or (raw is not None):
            self.cast = self._Cast(self._wheredat, self._db)
            self.seek = self._Seek(self._wheredat, self._db)
            self.markup = self._Markup(self._wheredat, self._db)

    def _push(self):
        DBDataWrite._push(self)
        self.cast.commit()
        self.seek.commit()
        self.markup.commit()

    def create(self, data=None):
        """Recorded.create(data=None) -> Recorded object"""
        DBDataWrite.create(self, data)
        self._wheredat = (self.chanid,self.starttime)
        self._pull()
        self.cast = self._Cast(self._wheredat, self._db)
        self.seek = self._Seek(self._wheredat, self._db)
        self.markup = self._Markup(self._wheredat, self._db)
        return self

    def delete(self, force=False, rerecord=False):
        """
        Recorded.delete(force=False, rerecord=False) -> retcode
                Informs backend to delete recording and all relevent data.
                'force' forces a delete if the file cannot be found.
                'rerecord' sets the file as recordable in oldrecorded
        """
        return self.getProgram().delete(force, rerecord)

    def open(self, type='r'):
        """Recorded.open(type='r') -> file or FileTransfer object"""
        return ftopen("myth://%s@%s/%s" % ( self.storagegroup,
                                            self.hostname,
                                            self.basename),
                      type, db=self._db,
                      chanid=self.chanid, starttime=self.starttime)

    def getProgram(self):
        """Recorded.getProgram() -> Program object"""
        be = FileOps(db=self._db)
        return be.getRecording(self.chanid, 
                    int(self.starttime.strftime('%Y%m%d%H%M%S')))

    def getRecordedProgram(self):
        """Recorded.getRecordedProgram() -> RecordedProgram object"""
        return RecordedProgram((self.chanid,self.progstart), db=self._db)

    def formatPath(self, path, replace=None):
        """
        Recorded.formatPath(path, replace=None) -> formatted path string
                'path' string is formatted as per mythrename.pl
        """
        for (tag, data) in (('T','title'), ('S','subtitle'),
                            ('R','description'), ('C','category'),
                            ('U','recgroup'), ('hn','hostname'),
                            ('c','chanid') ):
            tmp = unicode(self[data]).replace('/','-')
            path = path.replace('%'+tag, tmp)
        for (data, pre) in (   ('starttime','%'), ('endtime','%e'),
                               ('progstart','%p'),('progend','%pe') ):
            for (tag, format) in (('y','%y'),('Y','%Y'),('n','%m'),('m','%m'),
                                  ('j','%d'),('d','%d'),('g','%I'),('G','%H'),
                                  ('h','%I'),('H','%H'),('i','%M'),('s','%S'),
                                  ('a','%p'),('A','%p') ):
                path = path.replace(pre+tag, self[data].strftime(format))
        for (tag, format) in (('y','%y'),('Y','%Y'),('n','%m'),('m','%m'),
                              ('j','%d'),('d','%d')):
            path = path.replace('%o'+tag,
                    self['originalairdate'].strftime(format))
        path = path.replace('%-','-')
        path = path.replace('%%','%')
        path += '.'+self['basename'].split('.')[-1]

        # clean up for windows
        if replace is not None:
            for char in ('\\',':','*','?','"','<','>','|'):
                path = path.replace(char, replace)
        return path

class RecordedProgram( DBDataWrite ):

    """
    RecordedProgram(data=None, db=None, raw=None) -> RecordedProgram object
            'data' is a tuple containing (chanid, storagegroup)
    """
    _table = 'recordedprogram'
    _where = 'chanid=%s AND starttime=%s'
    _setwheredat = 'self.chanid,self.starttime'
    _defaults = {'title':'',     'subtitle':'',
                 'category':'',  'category_type':'',     'airdate':0,
                 'stars':0,      'previouslyshown':0,    'title_pronounce':'',
                 'stereo':0,     'subtitled':0,          'hdtv':0,
                 'partnumber':0, 'closecaptioned':0,     'parttotal':0,
                 'seriesid':'',  'originalairdate':'',   'showtype':u'',
                 'colorcode':'', 'syndicatedepisodenumber':'',
                 'programid':'', 'manualid':0,           'generic':0,
                 'first':0,      'listingsource':0,      'last':0,
                 'audioprop':u'','videoprop':u'',        
                 'subtitletypes':u''}
    _logmodule = 'Python RecordedProgram'

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized RecordedProgram at %s>" % hex(id(self))
        return u"<RecordedProgram '%s','%s' at %s>" % (self.title,
                self.starttime.strftime('%Y-%m-%d %H:%M:%S'), hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def create(self, data=None):
        """RecordedProgram.create(data=None) -> RecordedProgram object"""
        DBDataWrite.create(self, data)
        self._wheredat = (self.chanid, self.starttime)
        self._pull()
        return self

class OldRecorded( DBDataWrite, RECSTATUS ):
    """
    OldRecorded(data=None, db=None, raw=None) -> OldRecorded object
            'data' is a tuple containing (chanid, storagegroup)
    """

    _table = 'oldrecorded'
    _where = 'chanid=%s AND starttime=%s'
    _setwheredat = 'self.chanid,self.starttime'
    _defaults = {'title':'',     'subtitle':'',      
                 'category':'',  'seriesid':'',      'programid':'',
                 'findid':0,     'recordid':0,       'station':'',
                 'rectype':0,    'duplicate':0,      'recstatus':-3,
                 'reactivate':0, 'generic':0}
    _logmodule = 'Python OldRecorded'

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized OldRecorded at %s>" % hex(id(self))
        return u"<OldRecorded '%s','%s' at %s>" % (self.title,
                self.starttime.strftime('%Y-%m-%d %H:%M:%S'), hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def create(self, data=None):
        """OldRecorded.create(data=None) -> OldRecorded object"""
        DBDataWrite.create(self, data)
        self._wheredat = (self.chanid, self.starttime)
        self._pull()
        return self

    def setDuplicate(self, record=False):
        """
        OldRecorded.setDuplicate(record=False) -> None
                Toggles re-recordability
        """
        c = self._db.cursor(self._log)
        c.execute("""UPDATE oldrecorded SET duplicate=%%s
                     WHERE %s""" % self._where, \
                tuple([record]+list(self._wheredat)))
        FileOps(db=self._db).reschedule(0)

    def update(self, *args, **keywords):
        """OldRecorded entries can not be altered"""
        return
    def delete(self):
        """OldRecorded entries cannot be deleted"""
        return

class Job( DBDataWrite, JOBTYPE, JOBCMD, JOBFLAG, JOBSTATUS ):
    """
    Job(id=None, chanid=None, starttime=None, db=None, raw=None) -> Job object
            Can be initialized with a Job id, or chanid and starttime.
    """

    _table = 'jobqueue'
    _logmodule = 'Python Jobqueue'
    _defaults = {'id': None}

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized Job at %s>" % hex(id(self))
        return u"<Job '%s' at %s>" % (self.id, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, id=None, chanid=None, starttime=None, \
                        db=None, raw=None):
        self.__dict__['_where'] = 'id=%s'
        self.__dict__['_setwheredat'] = 'self.id,'

        if raw is not None:
            DBDataWrite.__init__(self, None, db, raw)
        elif id is not None:
            DBDataWrite.__init__(self, (id,), db, None)
        elif (chanid is not None) and (starttime is not None):
            self.__dict__['_where'] = 'chanid=%s AND starttime=%s'
            DBDataWrite.__init__(self, (chanid,starttime), db, None)
        else:
            DBDataWrite.__init__(self, None, db, None)

    def create(self, data=None):
        """Job.create(data=None) -> Job object"""
        id = DBDataWrite.create(self, data)
        self._where = 'id=%s'
        self._wheredat = (id,)
        return self

    def setComment(self,comment):
        """Job.setComment(comment) -> None, updates comment"""
        self.comment = comment
        self.update()

    def setStatus(self,status):
        """Job.setStatus(Status) -> None, updates status"""
        self.status = status
        self.update()

class Channel( DBDataWrite ):
    """Channel(chanid=None, data=None, raw=None) -> Channel object"""
    _table = 'channel'
    _where = 'chanid=%s'
    _setwheredat = 'self.chanid,'
    _defaults = {'icon':'none',          'videofilters':'',  'callsign':u'',
                 'xmltvid':'',           'recpriority':0,    'contrast':32768,
                 'brightness':32768,     'colour':32768,     'hue':32768,
                 'tvformat':u'Default',  'visible':1,        'outputfilters':'',
                 'useonairguide':0,      'atsc_major_chan':0,
                 'tmoffset':0,           'default_authority':'',
                 'commmethod':-1,        'atsc_minor_chan':0,
                 'last_record':datetime(1900,1,1)}
    _logmodule = 'Python Channel'

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized Channel at %s>" % hex(id(self))
        return u"<Channel '%s','%s' at %s>" % \
                        (self.chanid, self.name, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, chanid=None, db=None, raw=None):
        DBDataWrite.__init__(self, (chanid,), db, raw)

    def create(self, data=None):
        """Channel.create(data=None) -> Channel object"""
        DBDataWrite.create(self, data)
        self._wheredat = (self.chanid,)
        self._pull()
        return self

class Guide( DBData ):
    """
    Guide(data=None, db=None, raw=None) -> Guide object
            Data is a tuple of (chanid, starttime).
    """
    _table = 'program'
    _where = 'chanid=%s AND starttime=%s'
    _setwheredat = 'self.chanid,self.starttime'
    _logmodule = 'Python Guide'
    
    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized Guide at %s>" % hex(id(self))
        return u"<Guide '%s','%s' at %s>" % (self.title,
                self.starttime.strftime('%Y-%m-%d %H:%M:%S'), hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

    def __init__(self, data=None, db=None, raw=None, etree=None):
        if etree:
            db = DBCache(db)
            dat = {'chanid':etree[0]}
            attrib = etree[1].attrib
            for key in ('title','subTitle','category','seriesId',
                        'hostname','programId','airdate'):
                if key in attrib:
                    dat[key.lower()] = attrib[key]
            if 'stars' in attrib:
                dat['stars'] = locale.atof(attrib['stars'])
            if etree[1].text:
                dat['description'] = etree[1].text.strip()
            for key in ('startTime','endTime','lastModified'):
                if key in attrib:
                    dat[key.lower()] = datetime.strptime(
                                    attrib[key],'%Y-%m-%dT%H:%M:%S')

            raw = []
            for key in db.tablefields.program:
                if key in dat:
                    raw.append(dat[key])
                else:
                    raw.append(None)
            DBData.__init__(self, db=db, raw=raw)
        else:
            DBData.__init__(self, data=data, db=db, raw=raw)

    def record(self, type=Record.kAllRecord):
        rec = Record(db=self._db)
        for key in ('chanid','title','subtitle','description', 'category',
                    'seriesid','programid'):
            rec[key] = self[key]

        rec.startdate = self.starttime.date()
        rec.starttime = self.starttime-datetime.combine(rec.startdate, time())
        rec.enddate = self.endtime.date()
        rec.endtime = self.endtime-datetime.combine(rec.enddate, time())

        rec.station = Channel(self.chanid, db=self._db).callsign
        rec.type = type
        return rec.create()


#### MYTHVIDEO ####

class Video( DBDataWrite ):
    """Video(id=None, db=None, raw=None) -> Video object"""
    _table = 'videometadata'
    _where = 'intid=%s'
    _setwheredat = 'self.intid,'
    _defaults = {'subtitle':u'',             'director':u'Unknown',
                 'rating':u'NR',             'inetref':u'00000000',
                 'year':1895,                'userrating':0.0,
                 'length':0,                 'showlevel':1,
                 'coverfile':u'No Cover',    'host':u'',
                 'intid':None,               'homepage':u'',
                 'watched':False,            'category':'none',
                 'browse':True,              'hash':u'',
                 'season':0,                 'episode':0,
                 'releasedate':date(1,1,1),  'childid':-1,
                 'insertdate': datetime.now()}
    _logmodule = 'Python Video'
    _schema_value = 'mythvideo.DBSchemaVer'
    _schema_local = MVSCHEMA_VERSION
    _schema_name = 'MythVideo'
    _category_map = [{'None':0},{0:'None'}]

    def _fill_cm(self, name=None, id=None):
        if name:
            if name not in self._category_map[0]:
                c = self._db.cursor(self._log)
                q1 = """SELECT intid FROM videocategory WHERE category=%s"""
                q2 = """INSERT INTO videocategory SET category=%s"""
                if c.execute(q1, name) == 0:
                    c.execute(q2, name)
                    c.execute(q1, name)
                id = c.fetchone()[0]
                self._category_map[0][name] = id
                self._category_map[1][id] = name

        elif id:
            if id not in self._category_map[1]:
                c = self._db.cursor(self._log)
                if c.execute("""SELECT category FROM videocategory
                                               WHERE intid=%s""", id) == 0:
                    raise MythDBError('Invalid ID found in videometadata.category')
                else:
                    name = c.fetchone()[0]
                self._category_map[0][name] = id
                self._category_map[1][id] = name

    def _pull(self):
        DBDataWrite._pull(self)
        self._fill_cm(id=self.category)
        self.category = self._category_map[1][self.category]

    def _push(self):
        name = self.category
        self._fill_cm(name=name)
        self.category = self._category_map[0][name]
        DBDataWrite._push(self)
        self.category = name
        self.cast.commit()
        self.genre.commit()
        self.country.commit()

    def __repr__(self):
        return str(self).encode('utf-8')

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized Video at %s>" % hex(id(self))
        res = self.title
        if self.season and self.episode:
            res += u' - %dx%02d' % (self.season, self.episode)
        if self.subtitle:
            res += u' - '+self.subtitle
        return u"<Video '%s' at %s>" % (res, hex(id(self)))

    def __init__(self, id=None, db=None, raw=None):
        DBDataWrite.__init__(self, (id,), db, raw)
        if raw is not None:
            self._fill_cm(id=self.category)
            self.category = self._category_map[1][self.category]
        if (id is not None) or (raw is not None):
            self.cast = self._Cast((self.intid,), self._db)
            self.genre = self._Genre((self.intid,), self._db)
            self.country = self._Country((self.intid,), self._db)
            self.markup = self._Markup((self.filename,), self._db)

    def create(self, data=None):
        """Video.create(data=None) -> Video object"""
        c = self._db.cursor(self._log)
        fields = ' AND '.join(['%s=%%s' % f for f in \
                        ('title','subtitle','season','episode')])
        count = c.execute("""SELECT intid FROM videometadata WHERE %s""" %
                fields, (self.title, self.subtitle, self.season, self.episode))
        if count:
            id = c.fetchone()[0]
        else:
            if data:
                if 'category' in data:
                    self._fill_cm(name=data['category'])
                    data['category'] = self._category_map[0][data['category']]
            self._fill_cm(name=self.category)
            self.category = self._category_map[0][self.category]
            id = DBDataWrite.create(self, data)
        c.close()
        self._wheredat = (id,)
        self._pull()
        self.cast = self._Cast((self.intid,), self._db)
        self.genre = self._Genre((self.intid,), self._db)
        self.country = self._Country((self.intid,), self._db)
        self.markup = self._Markup((self.filename,), self._db)
        return self

    class _Cast( DBDataCRef ):
        _table = ['videometadatacast','videocast']
        _ref = ['idvideo']
        _cref = ['idcast','intid']

    class _Genre( DBDataCRef ):
        _table = ['videometadatagenre','videogenre']
        _ref = ['idvideo']
        _cref = ['idgenre','intid']

    class _Country( DBDataCRef ):
        _table = ['videometadatacountry','videocountry']
        _ref = ['idvideo']
        _cref = ['idcountry','intid']

    class _Markup( DBDataRef, MARKUP ):
        _table = 'filemarkup'
        _ref = ['filename',]

    def _open(self, type, mode='r',nooverwrite=False):
        """
        Open file pointer
        """
        sgroup = {  'filename':'Videos',        'banner':'Banners',
                    'coverfile':'Coverart',     'fanart':'Fanart',
                    'screenshot':'Screenshots', 'trailer':'Trailers'}
        if self._data is None:
            return None
        if type not in sgroup:
            raise MythFileError(MythError.FILE_ERROR,
                            'Invalid type passed to Video._open(): '+str(type))
        SG = self._db.getStorageGroup(sgroup[type], self.host)
        if len(SG) == 0:
            SG = self._db.getStorageGroup('Videos', self.host)
            if len(SG) == 0:
                raise MythFileError(MythError.FILE_ERROR,
                                    'Could not find MythVideo Storage Groups')
        return ftopen('myth://%s@%s/%s' % ( SG[0].groupname,
                                            self.host,
                                            self[type]),
                            mode, False, nooverwrite, self._db)

    def delete(self):
        """Video.delete() -> None"""
        if self._data is None:
            return
        self.cast.clean()
        self.genre.clean()
        self.country.clean()
        DBDataWrite.delete(self)

    def open(self,mode='r',nooverwrite=False):
        """Video.open(mode='r', nooverwrite=False)
                                -> file or FileTransfer object"""
        return self._open('filename',mode,nooverwrite)

    def openBanner(self,mode='r',nooverwrite=False):
        """Video.openBanner(mode='r', nooverwrite=False)
                                -> file or FileTransfer object"""
        return self._open('banner',mode,nooverwrite)

    def openCoverart(self,mode='r',nooverwrite=False):
        """Video.openCoverart(mode='r', nooverwrite=False)
                                -> file or FileTransfer object"""
        return self._open('coverfile',mode,nooverwrite)

    def openFanart(self,mode='r',nooverwrite=False):
        """Video.openFanart(mode='r', nooverwrite=False)
                                -> file or FileTransfer object"""
        return self._open('fanart',mode,nooverwrite)

    def openScreenshot(self,mode='r',nooverwrite=False):
        """Video.openScreenshot(mode='r', nooverwrite=False)
                                -> file or FileTransfer object"""
        return self._open('screenshot',mode,nooverwrite)

    def openTrailer(self,mode='r',nooverwrite=False):
        """Video.openTrailer(mode='r', nooverwrite=False)
                                -> file or FileTransfer object"""
        return self._open('trailer',mode,nooverwrite)

    def getHash(self):
        """Video.getHash() -> file hash"""
        if self.host is None:
            return None
        be = FileOps(self.host)
        hash = be.getHash(self.filename, 'Videos')
        return hash

    def fromFilename(self, filename):
        if self._wheredat is not None:
            return self
        self.filename = filename
        filename = filename[:filename.rindex('.')]
        for old in ('%20','_','.'):
            filename = filename.replace(old, ' ')

        sep = '(?:\s?(?:-|/)?\s?)?'
        regex1 = re.compile('^(.*[^s0-9])'+sep \
                           +'(?:s|(?:Season))?'+sep \
                           +'(\d{1,4})'+sep \
                           +'(?:[ex/]|Episode)'+sep \
                           +'(\d{1,3})'+sep \
                           +'(.*)$', re.I)

        regex2 = re.compile('(%s(?:Season%s\d*%s)*%s)$' \
                            % (sep, sep, sep, sep), re.I)

        match1 = regex1.search(filename)
        if match1:
            self.season = int(match1.group(2))
            self.episode = int(match1.group(3))
            self.subtitle = match1.group(4)

            title = match1.group(1)
            match2 = regex2.search(title)
            if match2:
                title = title[:match2.start()]
            self.title = title[title.rindex('/')+1:]
        else:
            title = filename[filename.rindex('/')+1:]
            for left,right in (('(',')'), ('[',']'), ('{','}')):
                while left in title:
                    lin = title.index(left)
                    rin = title.index(right,lin)
                    title = title[:lin]+title[rin+1:]
            self.title = title

        return self
        

class VideoGrabber( Grabber ):
    """
    VideoGrabber(mode, lang='en', db=None) -> VideoGrabber object
            'mode' can be of either 'TV' or 'Movie'
    """
    logmodule = 'Python MythVideo Grabber'

    def __init__(self, mode, lang='en', db=None):
        if mode == 'TV':
            Grabber.__init__(self, setting='mythvideo.TVGrabber', db=db)
        elif mode == 'Movie':
            Grabber.__init__(self, setting='mythvideo.MovieGrabber', db=db)
        else:
            raise MythError('Invalid MythVideo grabber')
        self._check_schema('mythvideo.DBSchemaVer',
                                MVSCHEMA_VERSION, 'MythVideo')
        self.append('-l',lang)
        self.override = {}

    def setOverride(self, data):
        # specify overrides for seachTitle function
        self.override.update(data)

    def searchTitle(self, title, year=None):
        """
        VideoGrabber.searchTitle(title, year=None)
                            -> tuple of tuples of (inetref, title, year)
        """
        if title.lower() in self.override:
            return ((self.override[title.lower()], title, None),)
        regex = re.compile('([0-9]+):(.+?)( \(([0-9]{4})\)\n|\n)')
        res = self.command('-M', '"%s"' %title)
        ret = []
        for m in regex.finditer(res):
            m = list(m.group(1,2,4))
            m[0] = int(m[0])
            if m[2]:
                m[2] = int(m[2])
            if year and m[2]:
                if m[2] != int(year):
                    continue
            ret.append(tuple(m))
        return ret

    def searchEpisode(self, title, subtitle):
        """
        VideoGrabber.searchEpisode(title, subtitle) -> (season, episode)
        """
        regex = re.compile("S(?P<season>[0-9]*)E(?P<episode>[0-9]*)")
        res = self.command('-N', '"%s"' % title, '"%s"' % subtitle)
        match = regex.match(res)
        if match:
            season = int(match.group('season'))
            episode = int(match.group('episode'))
            return (season, episode)
        else:
            return (None, None)

    def getData(self, inetref, season=None, episode=None, additional=False):
        """
        VideoGrabber.getData(inetref, season=None, episode=None, additional=False)
                    -> (data, cast, genre, country)
                    -> (data, cast, genre, country, additional)
                'season' and 'episode' are used only for TV grabbers
                'data' is a dictionary containing data matching the fields in a
                            Video object
                'cast', 'genre', and 'country' are tuples containing such
                'additional' is an optional response with any extra data
        """
        if season and episode:
            res = self.command('-D', inetref, season, episode)
        else:
            res = self.command('-D', str(inetref) )
        trans = {   'Title':'title',        'Subtitle':'subtitle',
                    'Year':'year',          'ReleaseDate':'releasedate',
                    'InetRef':'inetref',    'URL':'homepage',
                    'Director':'director',  'Plot':'plot',
                    'UserRating':'stars',   'MovieRating':'rating',
                    'Runtime':'length',     'Season':'season',
                    'Episode':'episode',    'Seriesid':'inetref',
                    'Coverart':'coverfile', 'Fanart':'fanart',
                    'Banner':'banner',      'Screenshot':'screenshot',
                    'Tagline':'tagline'}
        dat = {}
        cast = ()
        genre = ()
        country = ()
        adddict = {}
        for point in res.split('\n')[:-1]:
            if point.find(':') == -1:
                continue
            key,val = point.split(':',1)
            if key in trans:
                dat[trans[key]] = val
            elif key == 'Cast':
                cast = val.split(', ')
            elif key == 'Genres':
                genre = val.split(', ')
            elif key == 'Countries':
                country = val.split(', ')
            else:
                adddict[key] = val
        if 'releasedate' in dat:
            dat['releasedate'] = datetime.strptime(dat['releasedate'],\
                                                '%Y-%m-%d').date()
        if additional:
            return (dat, cast, genre, country, adddict)
        return (dat, cast, genre, country)

#### MYTHNETVISION ####

class NetVisionRSSItem( DBData ):
    """
    Represents a single program from the netvisionrssitems table
    """
    _table = 'netvisionrssitems'
    _where = 'feedtitle=%s AND title=%s'
    _setwheredat = 'self.feedtitle,self.title'
    _schema_value = 'NetvisionDBSchemaVer'
    _schema_local = NVSCHEMA_VERSION
    _schema_name = 'NetVision'
    
    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized NetVisionRSSItem at %s>" % hex(id(self))
        return u"<NetVisionRSSItem '%s@%s' at %s>" % \
                    (self.title, self.feedtitle, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

class NetVisionTreeItem( DBData ):
    """
    Represents a single program from the netvisiontreeitems table
    """
    _table = 'netvisiontreeitems'
    _where = 'feedtitle=%s AND path=%s'
    _setwheredat = 'self.feedtitle,self.path'
    _schema_value = 'NetvisionDBSchemaVer'
    _schema_local = NVSCHEMA_VERSION
    _schema_name = 'NetVision'

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized NetVisionTreeItem at %s>" % hex(id(self))
        return u"<NetVisionTreeItem '%s@%s' at %s>" % \
                    (self.path, self.feedtitle, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

class NetVisionSite( DBData ):
    """
    Represents a single site from the netvisionsites table
    """
    _table = 'netvisionsites'
    _where = 'name=%'
    _setwheredat = 'name,'
    _schema_value = 'NetvisionDBSchemaVer'
    _schema_local = NVSCHEMA_VERSION
    _schema_name = 'NetVision'

    def __str__(self):
        if self._wheredat is None:
            return u"<Uninitialized NetVisionSite at %s>" % hex(id(self))
        return u"<NetVisionSite '%s','%s' at %s>" % \
                    (self.name, self.url, hex(id(self)))

    def __repr__(self):
        return str(self).encode('utf-8')

class NetVisionGrabber( Grabber ):
    logmodule = 'Python MythNetVision Grabber'

    @staticmethod
    def grabberList(types='search,tree', db=None):
        db = DBCache(db)
        db._check_schema('NetvisionDBSchemaVer',
                                NVSCHEMA_VERSION, 'NetVision')
        c = db.cursor(self.log)
        log = MythLog('Python MythNetVision Grabber', db=db)
        host = gethostname()
        glist = []
        for t in types.split(','):
            c.execute("""SELECT name,commandline
                        FROM netvision%sgrabbers
                        WHERE host=%%s""" % t, (host,))
            for name,commandline in c.fetchall():
                glist.append(NetVisionGrabber(name, t, db, commandline))
        c.close()
        return glist

    def __init__(self, name, type, db=None, commandline=None):
        if type not in ('search','tree'):
            raise MythError('Invalid NetVisionGrabber() type')
        self.type = type
        self.name = name
        if commandline:
            Grabber.__init__(path=commandline, db=db)
        else:
            db = DBCache(db)
            self.log = MythLog(self.logmodule, db=self)
            if c.execute("""SELECT commandline
                            FROM netvision%sgrabbers
                            WHERE name=%%s AND host=%%s""" % type,
                                        (name, gethostname())) == 1:
                Grabber.__init__(path=c.fetchone()[0], db=db)
                c.close()
            else:
                c.close()
                raise MythError('NetVisionGrabber not found in database')

    def searchXML(self, title, page=1):
        return etree.fromstring(\
                        self.command('-p',page,'-S','"%s"' %title)).getroot()

    def treeXML(self):
        return etree.fromstring(self.command('-T'))

    def setUpdated(self):
        if self.type is not 'tree':
            raise MythError('Can only update tree-type grabbers')
        c = db.cursor(self.log)
        c.execute("""UPDATE netvision%sgrabbers SET update=NOW()
                     WHERE name=%%s AND host=%%s""" % type,
                     (self.name, gethostname()))
        c.close()


