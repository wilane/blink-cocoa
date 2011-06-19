# Copyright (C) 2010 AG Projects. See LICENSE for details.
#

"""
Blink account settings extensions.
"""

__all__ = ['AccountExtension', 'BonjourAccountExtension']

from sipsimple.account import BonjourMSRPSettings, MessageSummarySettings, MSRPSettings, RTPSettings, SIPSettings, TLSSettings, XCAPSettings
from sipsimple.configuration import Setting, SettingsGroup, SettingsObjectExtension
from sipsimple.configuration.datatypes import Hostname, MSRPConnectionModel, MSRPTransport, NonNegativeInteger

from configuration.datatypes import AccountSoundFile, AccountTLSCertificate, Digits, HTTPURL


class BonjourMSRPSettingsExtension(BonjourMSRPSettings):
    transport = Setting(type=MSRPTransport, default='tls')


class AudioSettingsExtension(SettingsGroup):
    auto_accept = Setting(type=bool, default=False)
    answer_delay = Setting(type=NonNegativeInteger, default=6)


class MessageSummarySettingsExtension(MessageSummarySettings):
    enabled = Setting(type=bool, default=True)


class MSRPSettingsExtension(MSRPSettings):
    connection_model = Setting(type=MSRPConnectionModel, default='relay')


class PSTNSettings(SettingsGroup):
    idd_prefix = Setting(type=Digits, default=None, nillable=True)
    prefix = Setting(type=Digits, default=None, nillable=True)


class RTPSettingsExtension(RTPSettings):
    inband_dtmf = Setting(type=bool, default=True)
    use_srtp_without_tls = Setting(type=bool, default=True)


class SIPSettingsExtension(SIPSettings):
    always_use_my_proxy = Setting(type=bool, default=True)
    register = Setting(type=bool, default=True)


class ServerSettings(SettingsGroup):
    settings_url = Setting(type=HTTPURL, default=None, nillable=True)
    conference_server = Setting(type=Hostname, default=None, nillable=True)


class SoundsSettings(SettingsGroup):
    audio_inbound = Setting(type=AccountSoundFile, default=AccountSoundFile(AccountSoundFile.DefaultSoundFile('sounds.audio_inbound')), nillable=True)


class TLSSettingsExtension(TLSSettings):
    certificate = Setting(type=AccountTLSCertificate, default=AccountTLSCertificate(AccountTLSCertificate.DefaultTLSCertificate('default.crt')))


class XCAPSettingsExtension(XCAPSettings):
    enabled = Setting(type=bool, default=True)


class AccountExtension(SettingsObjectExtension):
    order = Setting(type=int, default=0)

    audio = AudioSettingsExtension
    message_summary = MessageSummarySettingsExtension
    msrp = MSRPSettingsExtension
    pstn = PSTNSettings
    rtp = RTPSettingsExtension
    server = ServerSettings
    sip = SIPSettingsExtension
    sounds = SoundsSettings
    tls = TLSSettingsExtension
    xcap = XCAPSettingsExtension


class BonjourAccountExtension(SettingsObjectExtension):
    order = Setting(type=int, default=0)

    audio = AudioSettingsExtension
    msrp = BonjourMSRPSettingsExtension
    rtp = RTPSettingsExtension
    sounds = SoundsSettings
    tls = TLSSettingsExtension

