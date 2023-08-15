from xml.sax.saxutils import escape
import struct
from .const import LOGGER
from xml.dom import minidom


class ContextException(Exception):
    """An Exception class with context attached to it, so a caller can catch a
    (subclass of) ContextException, add some context with the exception's
    add_context method, and rethrow it to another callee who might again add
    information."""

    def __init__(self, msg, context=[]):
        self.msg = msg
        self.context = list(context)

    def __str__(self):
        if self.context:
            return '%s [context: %s]' % (self.msg, '; '.join(self.context))
        else:
            return self.msg

    def add_context(self, context):
        self.context.append(context)


class ParseException(ContextException):
    """An Exception for when something went wrong parsing the channel list."""
    pass


def _getint(buf, offset):
    """Helper function to extract a 16-bit little-endian unsigned from a char
    buffer 'buf' at offset 'offset'..'offset'+2."""
    x = struct.unpack('<H', buf[offset:offset + 2])
    return x[0]


class Channel(object):
    """Class representing a Channel from the TV's channel list."""

    @staticmethod
    def _parse_channel_list(channel_list):
        """Splits the binary channel list into channel entry fields and returns a list of Channels."""

        # The channel list is binary file with a 4-byte header, containing 2 unknown bytes and
        # 2 bytes for the channel count, which must be len(list)-4/124, as each following channel
        # is 124 bytes each. See Channel._parse_dat for how each entry is constructed.

        if len(channel_list) < 128:
            raise ParseException(('channel list is smaller than it has to be for at least '
                                  'one channel (%d bytes (actual) vs. 128 bytes' % len(channel_list)),
                                 ('Channel list: %s' % repr(channel_list)))

        if (len(channel_list)-4) % 124 != 0:
            raise ParseException(('channel list\'s size (%d) minus 128 (header) is not a multiple of '
                                  '124 bytes' % len(channel_list)),
                                 ('Channel list: %s' % repr(channel_list)))

        actual_channel_list_len = (len(channel_list)-4) / 124
        expected_channel_list_len = _getint(channel_list, 2)
        if actual_channel_list_len != expected_channel_list_len:
            raise ParseException(('Actual channel list length ((%d-4)/124=%d) does not equal expected '
                                  'channel list length (%d) as defined in header' % (
                                      len(channel_list),
                                      actual_channel_list_len,
                                      expected_channel_list_len))
                                 ('Channel list: %s' % repr(channel_list)))

        channels = {}
        pos = 4
        while pos < len(channel_list):
            chunk = channel_list[pos:pos+124]
            try:
                ch = Channel(chunk)
                channels[ch.dispno] = ch
            except ParseException as pe:
                pe.add_context('chunk starting at %d: %s' % (pos, repr(chunk)))
                raise pe

            pos += 124

        LOGGER.info('Parsed %d channels', len(channels))
        return channels

    def __init__(self, from_dat):
        """Constructs the Channel object from a binary channel list chunk."""
        if isinstance(from_dat, minidom.Node):
            self._parse_xml(from_dat)
        else:
            self._parse_dat(from_dat)

    def _parse_xml(self, root):
        try:
            self.ch_type = root.getElementsByTagName(
                'ChType')[0].childNodes[0].nodeValue
            self.major_ch = root.getElementsByTagName(
                'MajorCh')[0].childNodes[0].nodeValue
            self.minor_ch = root.getElementsByTagName(
                'MinorCh')[0].childNodes[0].nodeValue
            self.ptc = root.getElementsByTagName(
                'PTC')[0].childNodes[0].nodeValue
            self.prog_num = root.getElementsByTagName(
                'ProgNum')[0].childNodes[0].nodeValue
            self.dispno = self.major_ch
            self.title = ''
        except Exception:
            raise ParseException("Wrong XML document")

    def _parse_dat(self, buf):
        """Parses the binary data from a channel list chunk and initilizes the
        member variables."""

        # Each entry consists of (all integers are 16-bit little-endian unsigned):
        #   [2 bytes int] Type of the channel. I've only seen 3 and 4, meaning
        #                 CDTV (Cable Digital TV, I guess) or CATV (Cable Analog
        #                 TV) respectively as argument for <ChType>
        #   [2 bytes int] Major channel (<MajorCh>)
        #   [2 bytes int] Minor channel (<MinorCh>)
        #   [2 bytes int] PTC (Physical Transmission Channel?), <PTC>
        #   [2 bytes int] Program Number (in the mux'ed MPEG or so?), <ProgNum>
        #   [2 bytes int] They've always been 0xffff for me, so I'm just assuming
        #                 they have to be :)
        #   [4 bytes string, \0-padded] The (usually 3-digit, for me) channel number
        #                               that's displayed (and which you can enter), in ASCII
        #   [2 bytes int] Length of the channel title
        #   [106 bytes string, \0-padded] The channel title, in UTF-8 (wow)

        t = _getint(buf, 0)
        if t == 4:
            self.ch_type = 'CDTV'
        elif t == 3:
            self.ch_type = 'CATV'
        elif t == 2:
            self.ch_type = 'DTV'
        else:
            raise ParseException('Unknown channel type %d' % t)

        self.major_ch = _getint(buf, 2)
        self.minor_ch = _getint(buf, 4)
        self.ptc = _getint(buf, 6)
        self.prog_num = _getint(buf, 8)

        if _getint(buf, 10) != 0xffff:
            raise ParseException(
                'reserved field mismatch (%04x)' % _getint(buf, 10))

        self.dispno = buf[12:16].decode('utf-8').rstrip('\x00')

        title_len = _getint(buf, 22)
        self.title = buf[24:24+title_len].decode('utf-8')

    def display_string(self):
        """Returns a unicode display string, since both __repr__ and __str__ convert it
        to ascii."""

        return u'[%s] % 4s %s' % (self.ch_type, self.dispno, self.title)

    def __repr__(self):
        # return self.as_xml
        return '<Channel %s %s ChType=%s MajorCh=%d MinorCh=%d PTC=%d ProgNum=%d>' % \
            (self.dispno, repr(self.title), self.ch_type, self.major_ch, self.minor_ch, self.ptc,
             self.prog_num)

    @property
    def as_xml(self):
        """The channel list as XML representation for SetMainTVChannel."""

        return ('<?xml version="1.0" encoding="UTF-8" ?><Channel><ChType>%s</ChType><MajorCh>%d'
                '</MajorCh><MinorCh>%d</MinorCh><PTC>%d</PTC><ProgNum>%d</ProgNum></Channel>') % \
            (escape(self.ch_type), self.major_ch,
             self.minor_ch, self.ptc, self.prog_num)

    def as_params(self, chtype, sid):
        return {'ChannelListType': chtype, 'Channel': self.as_xml, 'SatelliteID': sid}
