# _sapi4.py  -  SAPI4 COM interface definitions for the Infovox 230 engine host.
#
# Interface layouts are taken from NVDA's own historical SAPI4 driver
# (source/synthDrivers/_sapi4.py, GPL, (C) NV Access) and trimmed to what the
# 32-bit host needs. GUIDs were cross-checked against the actual vtable IIDs
# found inside Ivx230nt.dll, so these match the engine exactly:
#     ITTSCentralW   {28016060-4A47-101B-931A-00AA0047BA4F}
#     ITTSEnumW      {6B837B20-4A47-101B-931A-00AA0047BA4F}
#     ITTSAttributesW{1287A280-4A47-101B-931A-00AA0047BA4F}
#     ITTSNotifySinkW{C0FA8F40-4A46-101B-931A-00AA0047BA4F}
#     ITTSBufNotifySink {E4963D40-C743-11cd-80E5-00AA003E4B50}
#     IAudioDest     {2EC34DA0-C743-11cd-80E5-00AA003E4B50}
#     IAudioDestNotifySink {ACB08C00-C743-11cd-80E5-00AA003E4B50}
#     CLSID_TTSEnumerator {D67C0280-C743-11cd-80E5-00AA003E4B50}
#
# This file is licensed under the GNU General Public License v2 (same terms as
# the code it derives from).

from ctypes import (
    cast, c_int, c_uint, c_ulong, c_ulonglong, c_wchar, c_wchar_p, c_void_p,
    c_char, HRESULT, POINTER, sizeof, Structure, windll, byref, c_ubyte,
)
from ctypes.wintypes import BOOL, BYTE, DWORD, WORD, LPCWSTR, FILETIME
from comtypes import GUID, IUnknown, STDMETHOD, COMMETHOD, CoCreateInstance, CLSCTX_ALL

S_OK = 0
SVFN_LEN = 262
LANG_LEN = 64
TTSI_NAMELEN = SVFN_LEN
TTSI_STYLELEN = SVFN_LEN

TTSDATAFLAG_TAGGED = 1

TTSATTR_MINPITCH = 0
TTSATTR_MAXPITCH = 0xFFFF
TTSATTR_MINSPEED = 0
TTSATTR_MAXSPEED = 0xFFFFFFFF
TTSATTR_MINVOLUME = 0
TTSATTR_MAXVOLUME = 0xFFFFFFFF

TTSFEATURE_VOLUME = 2
TTSFEATURE_SPEED = 4
TTSFEATURE_PITCH = 8
TTSFEATURE_FIXEDAUDIO = 1024

LANGID = WORD
QWORD = c_ulonglong


class VOICECHARSET(c_int):
    CHARSET_TEXT = 0
    CHARSET_IPAPHONETIC = 1
    CHARSET_ENGINEPHONETIC = 2


class LANGUAGEW(Structure):
    _fields_ = [("LanguageID", LANGID), ("szDialect", c_wchar * LANG_LEN)]


class TTSMODEINFOW(Structure):
    _fields_ = [
        ("gEngine", GUID),
        ("szMfgName", c_wchar * TTSI_NAMELEN),
        ("szProductName", c_wchar * TTSI_NAMELEN),
        ("gModeID", GUID),
        ("szModeName", c_wchar * TTSI_NAMELEN),
        ("language", LANGUAGEW),
        ("szSpeaker", c_wchar * TTSI_NAMELEN),
        ("szStyle", c_wchar * TTSI_STYLELEN),
        ("wGender", WORD),
        ("wAge", WORD),
        ("dwFeatures", DWORD),
        ("dwInterfaces", DWORD),
        ("dwEngineFeatures", DWORD),
    ]


TTSMODEINFO = TTSMODEINFOW


class SDATA(Structure):
    _fields_ = [("pData", c_void_p), ("dwSize", DWORD)]


class TTSMOUTH(Structure):
    _fields_ = [
        ("bMouthHeight", BYTE), ("bMouthWidth", BYTE), ("bMouthUpturn", BYTE),
        ("bJawOpen", BYTE), ("bTeethUpperVisible", BYTE),
        ("bTeethLowerVisible", BYTE), ("bTonguePosn", BYTE), ("bLipTension", BYTE),
    ]


def TextSDATA(text):
    d = SDATA()
    buf = c_wchar_p(text)
    d.pData = cast(buf, c_void_p)
    d.dwSize = (len(text) + 1) * sizeof(c_wchar)
    d._buf = buf  # keep a reference so it is not GC'd
    return d


class ITTSAttributesW(IUnknown):
    _iid_ = GUID("{1287A280-4A47-101B-931A-00AA0047BA4F}")
    _methods_ = [
        STDMETHOD(HRESULT, "PitchGet", [POINTER(WORD)]),
        STDMETHOD(HRESULT, "PitchSet", [WORD]),
        STDMETHOD(HRESULT, "RealTimeGet", [POINTER(DWORD)]),
        STDMETHOD(HRESULT, "RealTimeSet", [DWORD]),
        STDMETHOD(HRESULT, "SpeedGet", [POINTER(DWORD)]),
        STDMETHOD(HRESULT, "SpeedSet", [DWORD]),
        STDMETHOD(HRESULT, "VolumeGet", [POINTER(DWORD)]),
        STDMETHOD(HRESULT, "VolumeSet", [DWORD]),
    ]


class ITTSBufNotifySink(IUnknown):
    _iid_ = GUID("{E4963D40-C743-11cd-80E5-00AA003E4B50}")
    # implemented on our side; layout must match engine expectations
    _methods_ = [
        STDMETHOD(HRESULT, "TextDataDone", [QWORD, DWORD]),
        STDMETHOD(HRESULT, "TextDataStarted", [QWORD]),
        STDMETHOD(HRESULT, "BookMark", [QWORD, DWORD]),
        STDMETHOD(HRESULT, "WordPosition", [QWORD, DWORD]),
    ]


class ITTSCentralW(IUnknown):
    _iid_ = GUID("{28016060-4A47-101B-931A-00AA0047BA4F}")
    _methods_ = [
        STDMETHOD(HRESULT, "Inject", [LPCWSTR]),
        STDMETHOD(HRESULT, "ModeGet", [POINTER(TTSMODEINFOW)]),
        STDMETHOD(HRESULT, "Phoneme", [VOICECHARSET, DWORD, SDATA, POINTER(SDATA)]),
        STDMETHOD(HRESULT, "PosnGet", [POINTER(QWORD)]),
        STDMETHOD(HRESULT, "TextData",
                  [VOICECHARSET, DWORD, SDATA, c_void_p, GUID]),
        STDMETHOD(HRESULT, "ToFileTime", [POINTER(QWORD), POINTER(FILETIME)]),
        STDMETHOD(HRESULT, "AudioPause"),
        STDMETHOD(HRESULT, "AudioResume"),
        STDMETHOD(HRESULT, "AudioReset"),
        STDMETHOD(HRESULT, "Register", [c_void_p, GUID, POINTER(DWORD)]),
        STDMETHOD(HRESULT, "UnRegister", [DWORD]),
    ]


class ITTSNotifySinkW(IUnknown):
    _iid_ = GUID("{C0FA8F40-4A46-101B-931A-00AA0047BA4F}")
    _methods_ = [
        STDMETHOD(HRESULT, "AttribChanged", [DWORD]),
        STDMETHOD(HRESULT, "AudioStart", [QWORD]),
        STDMETHOD(HRESULT, "AudioStop", [QWORD]),
        STDMETHOD(HRESULT, "Visual",
                  [QWORD, c_wchar, c_wchar, DWORD, POINTER(TTSMOUTH)]),
    ]


class ITTSEnumW(IUnknown):
    _iid_ = GUID("{6B837B20-4A47-101B-931A-00AA0047BA4F}")


# Assigned after the class so Clone can reference ITTSEnumW itself.
ITTSEnumW._methods_ = [
    STDMETHOD(HRESULT, "Next",
              [c_ulong, POINTER(TTSMODEINFOW), POINTER(c_ulong)]),
    STDMETHOD(HRESULT, "Skip", [c_ulong]),
    STDMETHOD(HRESULT, "Reset"),
    STDMETHOD(HRESULT, "Clone", [POINTER(POINTER(ITTSEnumW))]),
    STDMETHOD(HRESULT, "Select",
              [GUID, POINTER(POINTER(ITTSCentralW)), POINTER(IUnknown)]),
]


class IAudio(IUnknown):
    _iid_ = GUID("{F546B340-C743-11cd-80E5-00AA003E4B50}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Flush"),
        COMMETHOD([], HRESULT, "LevelGet", (["out"], POINTER(DWORD), "pdwLevel")),
        COMMETHOD([], HRESULT, "LevelSet", (["in"], DWORD, "dwLevel")),
        COMMETHOD([], HRESULT, "PassNotify",
                  (["in"], c_void_p, "pNotifyInterface"),
                  (["in"], GUID, "IIDNotifyInterface")),
        COMMETHOD([], HRESULT, "PosnGet", (["out"], POINTER(QWORD), "pqwTimeStamp")),
        COMMETHOD([], HRESULT, "Claim"),
        COMMETHOD([], HRESULT, "UnClaim"),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "TotalGet", (["out"], POINTER(QWORD), "pqWord")),
        COMMETHOD([], HRESULT, "ToFileTime",
                  (["in"], POINTER(QWORD), "pqWord"),
                  (["out"], POINTER(FILETIME), "pFT")),
        COMMETHOD([], HRESULT, "WaveFormatGet", (["out"], POINTER(SDATA), "pdWFEX")),
        COMMETHOD([], HRESULT, "WaveFormatSet", (["in"], SDATA, "dWFEX")),
    ]


class IAudioDest(IUnknown):
    _iid_ = GUID("{2EC34DA0-C743-11cd-80E5-00AA003E4B50}")
    _methods_ = [
        COMMETHOD([], HRESULT, "FreeSpace",
                  (["out"], POINTER(DWORD), "pdwBytes"),
                  (["out"], POINTER(BOOL), "pfEOF")),
        COMMETHOD([], HRESULT, "DataSet",
                  (["in"], c_void_p, "pBuffer"), (["in"], DWORD, "dwSize")),
        COMMETHOD([], HRESULT, "BookMark", (["in"], DWORD, "dwMarkID")),
    ]


class IAudioDestNotifySink(IUnknown):
    _iid_ = GUID("{ACB08C00-C743-11cd-80E5-00AA003E4B50}")
    _methods_ = [
        STDMETHOD(HRESULT, "AudioStop", [WORD]),
        STDMETHOD(HRESULT, "AudioStart"),
        STDMETHOD(HRESULT, "FreeSpace", [DWORD, BOOL]),
        STDMETHOD(HRESULT, "BookMark", [DWORD, BOOL]),
    ]


CLSID_TTSEnumerator = GUID("{D67C0280-C743-11cd-80E5-00AA003E4B50}")
