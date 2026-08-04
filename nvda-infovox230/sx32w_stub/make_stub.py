#!/usr/bin/env python3
"""Emit a minimal 32-bit Windows PE DLL emulating the Rainbow Sentinel
SuperPro API (Sx32w.dll) used by the Infovox 230 TTS engine."""
import struct, sys
IMAGE_BASE=0x10000000; SECT_ALIGN=0x1000; FILE_ALIGN=0x200
CODE_ENTRY=bytes.fromhex("b801000000c20c00")            # mov eax,1; ret 0x0C
CODE_READ =bytes.fromhex("8b44240c66c700ffff33c0c20c00")# *data=0xFFFF; xor eax,eax; ret 0x0C
CODE_RET8 =bytes.fromhex("33c0c20800")                  # xor eax,eax; ret 8
CODE_RET4 =bytes.fromhex("33c0c20400")                  # xor eax,eax; ret 4
CODE_RET0 =bytes.fromhex("33c0c3")                      # xor eax,eax; ret
EXPORTS={
 "DllEntryPoint":CODE_ENTRY,"RNBOsproActivate":CODE_RET0,"RNBOsproCfgLibParams":CODE_RET0,
 "RNBOsproDecrement":CODE_RET0,"RNBOsproExtendedRead":CODE_RET0,"RNBOsproFindFirstUnit":CODE_RET8,
 "RNBOsproFindNextUnit":CODE_RET4,"RNBOsproFormatPacket":CODE_RET8,"RNBOsproGetFullStatus":CODE_RET0,
 "RNBOsproGetVersion":CODE_RET0,"RNBOsproInitialize":CODE_RET4,"RNBOsproOverwrite":CODE_RET0,
 "RNBOsproQuery":CODE_RET0,"RNBOsproRead":CODE_READ,"RNBOsproWrite":CODE_RET0}
ENTRY_NAME="DllEntryPoint"
def align(v,a): return (v+a-1)&~(a-1)
text=bytearray(); func_rva={}; text_rva=SECT_ALIGN; frag_off={}
for name,code in EXPORTS.items():
    key=bytes(code)
    if key not in frag_off:
        frag_off[key]=len(text); text+=code
    func_rva[name]=text_rva+frag_off[key]
text_vsize=len(text); text_raw=align(len(text),FILE_ALIGN); text+=b"\x00"*(text_raw-len(text))
rdata_rva=align(text_rva+text_vsize,SECT_ALIGN)
names=sorted(EXPORTS.keys()); n=len(names)
EXPDIR_SZ=40; eat_off=EXPDIR_SZ; enpt_off=eat_off+n*4; ord_off=enpt_off+n*4; str_off=ord_off+n*2
strings=bytearray()
def add_string(s):
    off=str_off+len(strings); strings.extend(s.encode("ascii")+b"\x00"); return off
dllname_rva=rdata_rva+add_string("sx32w.dll")
name_rvas=[rdata_rva+add_string(nm) for nm in names]
eat=b"".join(struct.pack("<I",func_rva[nm]) for nm in names)
enpt=b"".join(struct.pack("<I",rva) for rva in name_rvas)
ordt=b"".join(struct.pack("<H",i) for i in range(n))
expdir=struct.pack("<IIHHIIIIII",0,0,0,0,dllname_rva,1,n,n,rdata_rva+eat_off,rdata_rva+enpt_off)
expdir+=struct.pack("<I",rdata_rva+ord_off)
blob=expdir+eat+enpt+ordt+bytes(strings)
export_dir_size=len(blob); rdata_vsize=len(blob); rdata_raw=align(len(blob),FILE_ALIGN)
rdata=bytes(blob)+b"\x00"*(rdata_raw-len(blob))
num_sections=2; size_headers=align(0x40+4+20+0xE0+num_sections*0x28,FILE_ALIGN)
text_file_off=size_headers; rdata_file_off=text_file_off+text_raw
size_of_image=align(rdata_rva+rdata_vsize,SECT_ALIGN)
dos=bytearray(0x40); dos[0:2]=b"MZ"; struct.pack_into("<I",dos,0x3C,0x40)
pe_sig=b"PE\x00\x00"
file_hdr=struct.pack("<HHIIIHH",0x014C,num_sections,0,0,0,0xE0,0x2102)
opt=struct.pack("<HBBIIIIII",0x10B,9,0,text_raw,rdata_raw,0,func_rva[ENTRY_NAME],text_rva,rdata_rva)
opt+=struct.pack("<IIIHHHHHHIIIIHHIIIIII",IMAGE_BASE,SECT_ALIGN,FILE_ALIGN,5,0,0,0,5,0,0,
                 size_of_image,size_headers,0,2,0x0000,0x100000,0x1000,0x100000,0x1000,0,16)
datadirs=[(0,0)]*16; datadirs[0]=(rdata_rva,export_dir_size)
for rva,sz in datadirs: opt+=struct.pack("<II",rva,sz)
def section(name,vsize,vrva,raw_size,raw_ptr,chars):
    return struct.pack("<8sIIIIIIHHI",name.encode().ljust(8,b"\x00"),vsize,vrva,raw_size,raw_ptr,0,0,0,0,chars)
sect_text=section(".text",text_vsize,text_rva,text_raw,text_file_off,0x60000020)
sect_rdata=section(".rdata",rdata_vsize,rdata_rva,rdata_raw,rdata_file_off,0x40000040)
headers=bytes(dos)+pe_sig+file_hdr+opt+sect_text+sect_rdata
headers+=b"\x00"*(size_headers-len(headers))
out=headers+text+rdata
open(sys.argv[1] if len(sys.argv)>1 else "sx32w.dll","wb").write(out)
print("wrote %d bytes; %d exports; entry RVA 0x%X"%(len(out),n,func_rva[ENTRY_NAME]))
