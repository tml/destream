import os
import io
import errno
import tempfile

from shutil import copyfileobj
from subprocess import Popen, PIPE
from threading import Thread
from distutils.spawn import find_executable

from destream import Archive

__all__ = """
          ArchiveFile ArchiveTemp ExternalPipe make_seekable
          """.split()


class ArchiveFile(Archive):
    """
    Make an archive from a file-object
    """
    def __init__(self, fileobj=None, name=None, closefd=True):
        if not fileobj:
            if not name:
                raise TypeError("Either name, fileobj must be specified")
            fileobj = io.FileIO(name)
        elif not name and hasattr(fileobj, 'name'):
            name = fileobj.name
        Archive.__init__(self, name, fileobj, source=fileobj, closefd=closefd)


class ArchiveTemp(Archive):
    """
    Write down a file-object to a temporary file and make an archive from it
    """
    def __init__(self, fileobj, name=None):
        if isinstance(fileobj, Archive):
            if name is None: name = fileobj.realname
        else:
            name = fileobj.name
        tempdir = \
            (os.path.dirname(name) if isinstance(name, basestring) else None)
        try:
            self.tempfile = tempfile.NamedTemporaryFile(dir=tempdir)
        except OSError:
            self.tempfile = tempfile.NamedTemporaryFile()
        self.tempfile.writelines(fileobj)
        self.tempfile.seek(0)
        # NOTE: no need (and you shouldn't need) to close the temporary file,
        #       it will be automatically closed on __del__()
        fileio = io.FileIO(self.tempfile.fileno(), closefd=False)
        fileio.name = self.tempfile.name
        Archive.__init__(self, name, fileio, source=fileobj)


def make_seekable(fileobj):
    """
    If the file-object is not seekable, return  ArchiveTemp of the fileobject,
    otherwise return the file-object itself
    """
    if isinstance(fileobj, file):
        filename = fileobj.name
        fileobj = io.FileIO(fileobj.fileno(), closefd=False)
        fileobj.name = filename
    assert isinstance(fileobj, io.IOBase), \
        "fileobj must be an instance of io.IOBase or a file, got %s" \
        % type(fileobj)
    return fileobj if fileobj.seekable() \
        else ArchiveTemp(fileobj)


class ExternalPipe(Archive, Thread):
    """
    Pipe a file-object to a command and make an archive of the output
    """
    def __init__(self, name, stdin):
        assert type(self) is not ExternalPipe, \
            "This class can not be used in standalone"
        assert hasattr(self, '_command'), \
            "_command attribute is missing in class %s" % type(self)
        Thread.__init__(self)
        self.p = Popen(self._command, stdout=PIPE, stdin=PIPE, stderr=PIPE)
        Archive.__init__(self, name, fileobj=self.p.stdout, source=stdin)
        self.start()

    @classmethod
    def _check_availability(cls):
        assert cls is not ExternalPipe, \
            "This class can not be used in standalone"
        assert hasattr(cls, '_command'), \
            "_command attribute is missing in class %s" % cls
        commands = [cls._command[0]]
        if hasattr(cls, '__fallbackcommands__'):
            commands += cls.__fallbackcommands__
        existing_commands = filter(None, map(find_executable, commands))
        if not existing_commands:
            if len(commands) == 1:
                raise OSError(2, commands[0], "cannot find executable")
            else:
                raise OSError(2, commands[0],
                    "cannot find executable between: " + ", ".join(commands))
        cls._command[0] = existing_commands[0]

    def run(self):
        try:
            copyfileobj(self.source, self.p.stdin)
        except IOError, exc:
            # NOTE: regular exception when we close the pipe, just hide it
            if exc.errno == errno.EPIPE:
                pass
            else:
                raise
        self.p.stdin.close()
        self.p.wait()

    @property
    def closed(self):
        return self.p.stdout.closed

    def close(self):
        super(ExternalPipe, self).close()
        if self.p.poll() is None:
            self.p.terminate()
            self.join()
