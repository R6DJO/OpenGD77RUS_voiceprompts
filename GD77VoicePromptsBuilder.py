#!/usr/bin/env python3

import urllib.request
import json
import csv
import os, sys
import time
import os
import subprocess
import struct
import serial
import platform
import getopt, sys
import serial.tools.list_ports
import ntpath
import shutil
import webbrowser
import re
from ctypes import *
import enum
from dataclasses import dataclass

PROGRAM_VERSION = "0.0.3"

FLASH_SEND_SIZE = 8
MAX_USB_TRANSFERT_SIZE = 1024
MAX_TRANSFER_SIZE = MAX_USB_TRANSFERT_SIZE - FLASH_SEND_SIZE
VOICE_PROMPTS_SIZE_MAX = 0x28C00 ## max available FLASH space
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
overwrite = False
gain = '0'
atempo = '1.5'
atempoAlias = ""
removeSilenceAtStart = False
# PollyPro is not working
forceTTSMP3Usage = True

# Default write command
writeCommandChar = ord('W')

#FLASH_WRITE_SIZE = 2

PlatformsNames = [ "GD-77", "GD-77S", "DM-1801", "RD-5R", "DM-1801A", "MD-9600", "MD-UV380", "MD-380", "DM-1701", "MD-2017", "MD-UV390 Plus" ]

class PlatformModels(enum.Enum):
    PLATFORM_UNKNOWN = -1
    PLATFORM_GD77 = 0
    PLATFORM_GD77S = 1
    PLATFORM_DM1801 = 2
    PLATFORM_RD5R = 3
    PLATFORM_DM1801A = 4
    PLATFORM_MD9600 = 5
    PLATFORM_MDUV380 = 6
    PLATFORM_MD380 = 7
    PLATFORM_DM1701 = 8
    PLATFORM_MD2017 = 9
    PLATFORM_MDUV390 = 106

    def __int__(self):
        return self.value

class RadioInfoFeatures(enum.Enum):
    SCREEN_INVERTED = (1 << 0)
    DMRID_USES_VOICE_PROMPTS = (1 << 1)
    VOICE_PROMPTS_AVAILABLE = (1 << 2)

    def __int__(self):
        return self.value

class RadioInfoStruct(Structure):
    _pack_ = 1
    _fields_ = [('structVersion', c_uint),
                ('radioType', c_uint),
                ('gitRevision', c_char * 16),
                ('buildDateTime', c_char * 16),
                ('flashId', c_uint),
                ('features', c_ushort)]

platformModel = PlatformModels.PLATFORM_UNKNOWN
radioInfo = None;

###
# Check feature bit from RadioInfo's feature
###
def RadioInfoIsFeatureSet(feature):
    v = int(radioInfo.features)
    f = int(feature)

    if ((v & f) != 0):
        return True

    return False

###
# Read the RadioInfo, then fill the global structure
###
def readRadioInfo(ser):
    DataModeReadRadioInfo = 9
    sendbuffer = [0x0] * 8
    readbuffer = [0x0] * 64
    totalLength = 0
    radioInfoBuffer = []
    size = 8

    ser.flush()

    print("Read RadioInfo...")
    sendbuffer[0] = ord('R')
    sendbuffer[1] = DataModeReadRadioInfo
    sendbuffer[2] = 0
    sendbuffer[3] = 0
    sendbuffer[4] = 0
    sendbuffer[5] = 0
    sendbuffer[6] = ((size >> 8) & 0xFF);
    sendbuffer[7] = ((size >> 0) & 0xFF);

    ret = ser.write(sendbuffer)
    if (ret != 8):
        print("ERROR: write() wrote " + ret + " bytes")
        return False

    while (ser.in_waiting == 0):
        time.sleep(0.2)

    readbuffer = ser.read(ser.in_waiting)

    header = ord('R')

    if (readbuffer[0] == header):
        totalLength = (readbuffer[1] << 8) + (readbuffer[2] << 0)
        radioInfoBuffer[0:] = readbuffer[3:]

    else:
        return False

    if (totalLength > 0):
        ## Check about RadioInfo version and upgrade if possible
        ## Latest version is 0x03
        if (radioInfoBuffer[0] == 0x01):
            radioInfoBuffer += [0x00, 0x00] ## features  set to 0
        elif (radioInfoBuffer[0] == 0x02):
            radioInfoBuffer += [0x00]; ## convert old screenInverted to features

        global radioInfo
        radioInfo = RadioInfoStruct.from_buffer(bytearray(radioInfoBuffer))

        ##print(radioInfoBuffer)
        #print("   * structVersion:", radioInfo.structVersion)
        #print("   * radioType:", radioInfo.radioType)
        #print("   * gitRevision:", radioInfo.gitRevision.decode("utf-8"))
        #print("   * buildDateTime:", radioInfo.buildDateTime.decode("utf-8"))
        #print("   * flashId:", hex(radioInfo.flashId))
        #print("   * features:", hex(radioInfo.features))

        global platformModel
        platformModel = PlatformModels(radioInfo.radioType)

        return True

    return False

def serialInit(serialDev):
    ser = serial.Serial()
    ser.port = serialDev
    ser.baudrate = 115200
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_ONE
    ##
    ## Non-blocking read/write
    ser.timeout = 0
    ser.write_timeout = 0
    ser.read_timeout = 0
    ##
    ##
    #ser.xonxoff = 0
    #ser.rtscts = 0

    try:
        ser.open()
    except serial.SerialException as err:
        print(str(err))
        sys.exit(1)
    return ser

def getMemoryArea(ser,buf,mode,bufStart,radioStart,length):
    snd = bytearray(FLASH_SEND_SIZE)
    snd[0] = ord('R')
    snd[1] = mode
    bufPos = bufStart
    radioPos = radioStart
    remaining = length
    while (remaining > 0):
        batch = min(remaining, MAX_TRANSFER_SIZE)

        snd[2] = (radioPos >> 24) & 0xFF
        snd[3] = (radioPos >> 16) & 0xFF
        snd[4] = (radioPos >>  8) & 0xFF
        snd[5] = (radioPos >>  0) & 0xFF
        snd[6] = (batch >> 8) & 0xFF
        snd[7] = (batch >> 0) & 0xFF

        ret = ser.write(snd)

        while (ser.out_waiting > 0):
            time.sleep(0)

        time.sleep(0.001) ## Give it a little bit of time to encode

        while (ser.in_waiting == 0):
            time.sleep(0)

        rcv = ser.read(ser.in_waiting)
        if (rcv[0] == snd[0]):
            gotBytes = (rcv[1] << 8) + rcv[2]
            for i in range(0,gotBytes):
                buf[bufPos] = rcv[i+3]
                bufPos += 1
            radioPos += gotBytes
            remaining -= gotBytes
        else:
            sys.exit("ABORT: Read ERROR (error at rcv[0]: " + str(rcv[0]) + ")")

    return True

def sendCommand(ser,commandNumber, x_or_command_option_number, y, iSize, alignment, isInverted, message):
    # snd allocation? len 64 or 32? or 23?
    snd = bytearray(7 + 21)
    snd[0] = ord('C')
    snd[1] = commandNumber
    snd[2] = x_or_command_option_number
    snd[3] = y
    snd[4] = iSize
    snd[5] = alignment
    snd[6] = isInverted
    # copy message to snd[7] (max 16 bytes)
    i = 7
    for c in message:
        if (i > 7+21-1):
            break
        snd[i] = ord(c)
        i += 1
    ser.flush()
    ret = ser.write(snd)
    if (ret != 7 + 21): # length?
        print("ERROR: write() wrote " + str(ret) + " bytes")
        return False
    while (ser.in_waiting == 0):
        time.sleep(0)
    rcv = ser.read(ser.in_waiting)
    return len(rcv) > 2 and rcv[1] == snd[1]

def wavSendData(ser,buf,radioStart,length):
    snd = bytearray(MAX_USB_TRANSFERT_SIZE)
    snd[0] = writeCommandChar
    snd[1] = 7#data type 7
    bufPos = 0
    radioPos = radioStart
    remaining = length
    while (remaining > 0):
        transferSize = min(remaining, MAX_TRANSFER_SIZE)

        snd[2] = (radioPos >> 24) & 0xFF
        snd[3] = (radioPos >> 16) & 0xFF
        snd[4] = (radioPos >>  8) & 0xFF
        snd[5] = (radioPos >>  0) & 0xFF
        snd[6] = (transferSize >>  8) & 0xFF
        snd[7] = (transferSize >>  0) & 0xFF
        snd[FLASH_SEND_SIZE:FLASH_SEND_SIZE + transferSize] = buf[bufPos:bufPos + transferSize]

        ## NOTE: it's not possible to specify the number of bytes to be written, hence a new tailored buffer is needed
        xmitBuffer = snd[0:FLASH_SEND_SIZE + transferSize]

        ret = ser.write(xmitBuffer)

        while (ser.out_waiting > 0):
            time.sleep(0)

        while (ser.in_waiting == 0):
            time.sleep(0)

        rcv = ser.read(ser.in_waiting)
        if (rcv[0] != snd[0]):
            sys.exit("ABORT: Send ERROR: at " + str(radioPos))

        bufPos += transferSize
        radioPos += transferSize
        remaining -= transferSize

    return True

def convert2AMBE(ser,infile,outfile):
    with open(infile,'rb') as f:
        ambBuf = bytearray(16 * 1024)# arbitary 16k buffer
        buf = bytearray(f.read())
        f.close();
        sendCommand(ser,1, 0, 0, 0, 0, 0, "") # Clear Screen
        sendCommand(ser,2, 0, 0, 2, 1, 0, "Кодировка") # Write line at line #0, front size 3, centered
        sendCommand(ser,2, 0, 16, 3, 1, 0, "Сжатие через AMBE") # Write line at line #16, front size 3, centered
        sendCommand(ser,2, 0, 39, 0, 1, 0, ntpath.basename(infile)[:-4]) # Write prompt name line at line #32, front size 0 (6x8 regular), centered
        sendCommand(ser,3, 0, 0, 0, 0, 0, "") # Render the screen
        wavBufPos = 0

        bufLen = len(buf)
        ambBufPos=0;
        ambFrameBuf = bytearray(27)
        startPos=0
        #if (infile[0:11] !="PROMPT_SPACE"):
        #    stripSilence = True;

        if (removeSilenceAtStart==True):
            while (startPos<len(buf) and  buf[startPos]==0 and buf[(startPos+1)]==0):
               startPos = startPos + 2;
            if (startPos == len(buf)):
                startPos = 0

        print("Compress to AMBE " + infile + " pos:+" + str(startPos));

        wavBufPos = startPos

        while (wavBufPos < bufLen):
            #print('.', end='')
            sendCommand(ser,6, 6, 0, 0, 0, 0,  "") # soundInit()
            transferLen = min(960, (bufLen - wavBufPos))
            #print("sent " + str(transferLen));
            wavSendData(ser, buf[wavBufPos:wavBufPos + transferLen], 0, transferLen)
            time.sleep(0.005)
            getMemoryArea(ser, ambFrameBuf, 8, 0, 0, 27) # mode 8 is read from AMBE
            ambBuf[ambBufPos:ambBufPos+27] = ambFrameBuf
            wavBufPos = wavBufPos + 960
            ambBufPos = ambBufPos + 27

        with open(outfile,'wb') as f:
            f.write(ambBuf[0:ambBufPos])

        #print("")#newline


def convertToRaw(inFile,outFile):
    print("ConvertToRaw "+ inFile + " -> " + outFile + " gain="+gain + " tempo="+atempo)
    callArgs = ['ffmpeg','-y','-i', inFile,'-filter:a','atempo=+'+atempo+',volume='+gain+'dB','-ar','8000','-f','s16le',outFile]
    if os.name == 'nt':
        subprocess.call(callArgs, creationflags=CREATE_NO_WINDOW)#'-af','silenceremove=1:0:-50dB'
    elif os.name == 'posix':
        subprocess.call(callArgs)#'-af','silenceremove=1:0:-50dB'

def downloadPollyPro(voiceName,fileStub,promptText,speechSpeed):
    global atempo
    retval=True
    hasDownloaded = False
    myobj = {'text-input': promptText,
             'voice':voiceName,
             'format':'mp3',# mp3 or ogg_vorbis or json
             'frequency':'22050',
             'effect':speechSpeed}

    data = urllib.parse.urlencode(myobj)
    data = data.encode('ascii')

    mp3FileName = voiceName + os.path.sep + fileStub + ".mp3"
    rawFileName = voiceName + os.path.sep + "tempo_" + atempo + os.path.sep + fileStub + ".raw"
    ambeFileName = voiceName + os.path.sep + "tempo_" + atempo + os.path.sep + fileStub + ".amb"

    if (not os.path.exists(mp3FileName) or overwrite==True):
        with urllib.request.urlopen("https://voicepolly.pro/speech-converter.php", data) as f:
            resp = f.read().decode('utf-8')
            print("PollyPro: Downloading synthesised speech for text: \"" + promptText + "\" -> " + mp3FileName)
            if resp.endswith('.mp3'):
                with urllib.request.urlopen(resp) as response, open(mp3FileName, 'wb') as out_file:
                    audioData = response.read() # a `bytes` object
                    out_file.write(audioData)
                    hasDownloaded = True
                    retval = True
            else:
                print("Error requesting sound " + resp)
                retval=False
#    else:
#        print("Download skipping " + file_name)

    if (hasDownloaded == True or not os.path.exists(rawFileName) or overwrite == True):
        convertToRaw(mp3FileName,rawFileName)
        if (os.path.exists(ambeFileName)):
            os.remove(ambeFileName)# ambe file is now out of date, so delete it

    return retval

def downloadTTSMP3(voiceName,fileStub,promptText):
    global atempo
    myobj = {'msg': promptText,
             'lang':voiceName,
             'source':'ttsmp3.com'}

    data = urllib.parse.urlencode(myobj)
    myStr = str.replace(data,"+","%20") #hacky fix because urlencode is not encoding spaces to %20
    data = myStr.encode('ascii')

    mp3FileName = voiceName + os.path.sep + fileStub + ".mp3"
    rawFileName = voiceName + os.path.sep + "tempo_" + atempo + os.path.sep + fileStub + ".raw"
    ambeFileName = voiceName + os.path.sep + "tempo_" + atempo + os.path.sep + fileStub + ".amb"

    hasDownloaded = False

    if (not os.path.exists(mp3FileName) or overwrite==True):
        print("Download TTSMP3 " +  promptText)

        with urllib.request.urlopen("https://ttsmp3.com/makemp3_new.php", data) as f:
            resp = f.read().decode('utf-8')
            print("TTSMP3: Downloading synthesised speech for text: \"" + promptText + "\" -> " + mp3FileName)
            print(resp)
            data = json.loads(resp)
            if (data['Error'] == 0):
                print(data['URL'])
                # Download the file from `url` and save it locally under `file_name`:
                with urllib.request.urlopen(data['URL']) as response, open(mp3FileName, 'wb') as out_file:
                    mp3data = response.read() # a `bytes` object
                    out_file.write(mp3data)
                    ## need to resample to 8kHz sample rate because ttsmp3 files are 22.05kHz
                    out_file.close()
                    hasDownloaded = True

            else:
                print("Error requesting sound")
                return False

    if (hasDownloaded == True or not os.path.exists(rawFileName) or overwrite == True):
        convertToRaw(mp3FileName,rawFileName)
        if (os.path.exists(ambeFileName)):
            os.remove(ambeFileName)# ambe file is now out of date, so delete it

    return True

def downloadSpeechForWordList(filename,voiceName):
    retval = True
    speechSpeed="normal"

    with open(filename,"r",encoding='utf-8') as csvfile:
        reader = csv.DictReader(filter(lambda row: row[0]!='#', csvfile))
        for row in reader:
            promptName = row['PromptName'].strip()

            speechPrefix = row['PromptSpeechPrefix'].strip()

            ## PollyPro is not working.
            if ((forceTTSMP3Usage == False) and (speechPrefix != "") and False):
                #Use VoicePolly as its not a special SSML that it doesnt handle
                if (speechPrefix.find("<prosody rate=")!=-1):
                    matchObj = re.search(r'\".*\"',speechPrefix)
                    if (matchObj):
                        speechSpeed = matchObj.group(0)[1:-1]

                downloadPollyPro(voiceName, promptName, row['PromptText'], speechSpeed)
            else:
                promptTTSText = row['PromptSpeechPrefix'].strip() +  row['PromptText'] + row['PromptSpeechPostfix'].strip()

                if (downloadTTSMP3(voiceName,promptName,promptTTSText)==False):
                    retval=False
                    break

    return retval

def encodeFile(ser,fileStub):
    if ((not os.path.exists(fileStub+".amb")) or overwrite==True):
        convert2AMBE(ser,fileStub+".raw",fileStub+".amb")
        #os.remove(fileStub+".raw")
##    else:
##       print("Encode skipping " + fileStub)

def encodeWordList(ser,filename,voiceName,forceReEncode):
    global atempo

    if (readRadioInfo(ser)):
        if (platformModel == PlatformModels.PLATFORM_MD9600) or (platformModel == PlatformModels.PLATFORM_MDUV380) or (platformModel == PlatformModels.PLATFORM_MD380) or (platformModel == PlatformModels.PLATFORM_DM1701) or (platformModel == PlatformModels.PLATFORM_MD2017):
            global writeCommandChar
            writeCommandChar = ord('X')

        print("Encoding using a {}".format(PlatformsNames[int(platformModel)]))

        with open(filename,"r",encoding='utf-8') as csvfile:
            sendCommand(ser,0, 0, 0, 0, 0, 0, "") # show CPS screen as this disables the radio etc
            sendCommand(ser,1, 0, 0, 0, 0, 0, "") # Clear Screen
            sendCommand(ser,3, 0, 0, 0, 0, 0, "") # Render the screen
            sendCommand(ser,6, 5, 0, 0, 0, 0,  "") # codecInitInternalBuffers()
            reader = csv.DictReader(filter(lambda row: row[0]!='#', csvfile))
            for row in reader:
                promptName = row['PromptName'].strip()
                fileStub = voiceName + os.path.sep + "tempo_" + atempo + os.path.sep + promptName


                encodeFile(ser,fileStub)

            sendCommand(ser,5, 0, 0, 0, 0, 0, "") # close CPS screen
    else:
        print("ERROR: unable to retrieve RadioInfo.")
        sys.exit(1)

def buildDataPack(filename,voiceName,outputFileName):
    flavors = [ "UV380-like", "monochrome" ]
    for flavor in flavors:
        print("Building " + flavor + " ...")
        promptsDict={}#create an empty dictionary
        with open(filename,"r",encoding='utf-8') as csvfile:
            reader = csv.DictReader(filter(lambda row: row[0]!='#', csvfile))
            for row in reader:
                promptName = row['PromptName'].strip()
                if (((flavor == "monochrome") and (promptName.startswith("theme_"))) == False):
                    infile = voiceName + os.path.sep + "tempo_" + atempo + os.path.sep + promptName + ".amb"
                    with open(infile,'rb') as f:
                        promptsDict[promptName] = bytearray(f.read())
                        f.close()
        MAX_PROMPTS = (341 if (flavor == "monochrome") else 378) ## 10 free each as of 2023 09 22
        headerTOCSize = (MAX_PROMPTS * 4) + 4 + 4
        outBuf = bytearray(headerTOCSize)
        outBuf[0:3]  = bytes([0x56, 0x50, 0x00, 0x00])#Magic number
        outBuf[4:7]  = bytes([(0x0A if (flavor == "monochrome") else 0x0B), 0x00, 0x00, 0x00])#Version number
        outBuf[8:11] = bytes([0x00, 0x00, 0x00, 0x00])#First prompt audio is at offset zero
        bufPos=12;
        cumulativelength=0;
        for prompt in promptsDict:
            cumulativelength = cumulativelength + len(promptsDict[prompt]);
            outBuf[bufPos+3] = (cumulativelength >> 24) & 0xFF
            outBuf[bufPos+2] = (cumulativelength >> 16) & 0xFF
            outBuf[bufPos+1] = (cumulativelength >>  8) & 0xFF
            outBuf[bufPos+0] = (cumulativelength >>  0) & 0xFF
            bufPos = bufPos + 4

        #outputFileName = voiceName+'/voice_prompts_'+voiceName+'.bin'
        filenameVPR, fileExtension = os.path.splitext(outputFileName)
        flavoredFilename = filenameVPR + "_" + flavor + fileExtension
        with open(flavoredFilename, 'wb') as f:
            f.write(outBuf[0:headerTOCSize])#Should be headerTOCSize
            for prompt in promptsDict:
                f.write(promptsDict[prompt])

        print("Built voice pack " + flavoredFilename);

        ## Check file size
        fileSize = os.path.getsize(flavoredFilename)
        if fileSize > VOICE_PROMPTS_SIZE_MAX:
            errorMsg = "ERROR: VPR file '{}' is too big ({} bytes, but max is {} bytes, delta: {} bytes). File deleted.".format(flavoredFilename, fileSize, VOICE_PROMPTS_SIZE_MAX, (fileSize - VOICE_PROMPTS_SIZE_MAX))
            print(errorMsg)
            with open(r"../../LanguagesFilesDeleted.txt", "a") as fErrorLog:
                fErrorLog.write(errorMsg)
                fErrorLog.write("\n")
            os.remove(flavoredFilename)


def usage(message=""):
    print("GD-77 voice prompts creator. v" + PROGRAM_VERSION)
    if (message != ""):
        print()
        print(message)
        print()

    print("Usage:  " + ntpath.basename(sys.argv[0]) + " [OPTION]")
    print("")
    print("    -h Display this help text,")
    print("    -c Configuration file (csv) - using this overrides all other options")
    print("    -f=<worlist_csv_file> : Wordlist file. Required for all functions")
    ##print("    -n=<Voice_name>       : Voice name for synthesised speech from Voicepolly.pro and temporary folder name")
    ##print("    -s                    : Download synthesised speech from Voicepolly.pro")
    print("    -T                    : Download synthesised speech from ttsmp3.com")
    print("    -e                    : Encode previous download synthesised speech files, using the GD-77")
    print("    -b                    : Build voice prompts data pack from Encoded spech files ")
    print("    -d=<device>           : Use the specified device as serial port,")
    print("    -o                    : Overwrite existing files")
    print("    -g=gain               : Audio level gain adjust in db.  Default is 0, but can be negative or positive numbers")
    print("    -t=tempo              : Audio tempo (from 0.5 to 2).  Default is {}".format(atempo))
    print("    -A=alias              : use alias instead of speed number into the resulting filename")
    print("    -r                    : Remove silence from beginning of audio files")
    print("")

def main():
    global overwrite
    global gain
    global atempo
    global atempoAlias
    global removeSilenceAtStart, forceTTSMP3Usage

    fileName   = ""#wordlist_english.csv"
    outputName = ""#voiceprompts.bin"
    voiceName = ""#Matthew or Nicole etc
    configName = ""

    # Default tty
    if (platform.system() == 'Windows'):
        serialDev = "COM71"
    else:
        serialDev = "/dev/ttyACM0"
    #Automatically search for the OpenGD77 device port
    for port in serial.tools.list_ports.comports():
        if (port.description.find("OpenGD77")==0):
            #print("Found OpenGD77 on port "+port.device);
            serialDev = port.device

    # Command line argument parsing
    try:
        ##opts, args = getopt.getopt(sys.argv[1:], "hof:n:seb:d:c:g:Tt:")
        opts, args = getopt.getopt(sys.argv[1:], "hof:eb:d:c:g:Tt:A:")
    except getopt.GetoptError as err:
        print(str(err))
        usage("")
        sys.exit(2)

    if os.name == 'nt':
        if (str(shutil.which("ffmpeg.exe")).find("ffmpeg") == -1):
            usage("ERROR: You must install ffmpeg. See https://www.ffmpeg.org/download.html")
            #webbrowser.open("https://www.ffmpeg.org/download.html")
            sys.exit(2)
    elif os.name == 'posix':
        if (str(shutil.which("ffmpeg")).find("ffmpeg") == -1):
            usage("ERROR: You must install ffmpeg. See https://www.ffmpeg.org/download.html")
            #webbrowser.open("https://www.ffmpeg.org/download.html")
            sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h"):
            usage()
            sys.exit(2)
        elif opt in ("-f"):
            fileName = arg
        #elif opt in ("-n"):
        #    voiceName = arg
        elif opt in ("-d"):
            serialDev = arg
        elif opt in ("-c"):
            configName = arg
        elif opt in ("-o"):
            overwrite = True
        elif opt in ("-g"):
            gain = arg
        elif opt in ("-r"):
            removeSilenceAtStart = arg
        elif opt in ("-T"):
            forceTTSMP3Usage = True
        elif opt in ('-t'):
            atempo = arg
        elif opt in ('-A'):
            atempoAlias = arg

    if (configName!=""):
        print("Using Config file: {}...".format(configName))

        with open(configName,"r",encoding='utf-8') as csvfile:
            reader = csv.DictReader(filter(lambda row: row[0]!='#', csvfile))
            for row in reader:
                wordlistFilename = row['Wordlist_file'].strip()
                voiceName = row['Voice_name'].strip()
                voicePackName = row['Voice_pack_name'].strip()
                download = row['Download'].strip()
                encode = row['Encode'].strip()
                createPack = row['Createpack'].strip()
                gain = row['Volume_change_db'].strip()
                rs = row['Remove_silence'].strip()
                cfg_atempo = row['Audio_tempo'].strip()

                ## Add audio tempo value to the filename
                voicePackName = voicePackName.replace('.vpr', '-' + (atempoAlias if len(atempoAlias) > 0 else atempo) + '.vpr');

                ## If Audio_tempo is not set, use the default value
                if cfg_atempo != '':
                    atempo = cfg_atempo

                print("Processing " + wordlistFilename+" "+voiceName+" "+voicePackName)

                if not os.path.exists(voiceName):
                    print("Creating folder " + voiceName + " for voice files")
                    os.mkdir(voiceName);

                if not os.path.exists(voiceName + os.path.sep + "tempo_" + atempo):
                    print("Creating folder " + voiceName + os.path.sep + "tempo_" + atempo + " for temporary files")
                    os.mkdir(voiceName + os.path.sep + "tempo_" + atempo);

                if (rs=='y' or rs=='Y'):
                    removeSilenceAtStart = True
                else:
                    removeSilenceAtStart = False

                if (download=='y' or download=='Y'):
                    if (downloadSpeechForWordList(wordlistFilename,voiceName)==False):
                     sys.exit(2)

                if (encode=='y' or encode=='Y'):
                    ser = serialInit(serialDev)

                    encodeWordList(ser,wordlistFilename,voiceName,True)
                    if (ser.is_open):
                        ser.close()
                if (createPack=='y' or createPack=='Y'):
                    buildDataPack(wordlistFilename,voiceName,voicePackName)

        sys.exit(0)


    if (fileName=="" or voiceName==""):
        usage("ERROR: Filename and Voicename must be specified for all operations")
        sys.exit(2)

    if not os.path.exists(voiceName):
        print("Creating folder " + voiceName + " for temporary files")
        os.mkdir(voiceName);

    #for opt, arg in opts:
    #    if opt in ("-s"):
    #        if (downloadSpeechForWordList(fileName,voiceName)==False):
    #            sys.exit(2)

    for opt, arg in opts:
        if opt in ("-e"):
            ser = serialInit(serialDev)
            encodeWordList(ser,fileName,voiceName,True)
            if (ser.is_open):
                ser.close()

    for opt, arg in opts:
        if opt in ("-b"):
            outputName = arg
            buildDataPack(fileName,voiceName,outputName)

main()
sys.exit(0)
