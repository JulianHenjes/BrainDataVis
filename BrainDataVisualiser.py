# Python 3.6.2, 64-bit
# Requires ffmpeg
# Dependencies:
# imageio
# imageio_ffmpeg
# pillow
# cv2
# numpy
# pygame
# radon - For Quality Assurance Metrics Only

import tkinter as tk
from PIL import ImageTk, Image
import cv2
import numpy as np
import os
import threading
import time
import pygame.mixer as mixer
from enum import Enum
import xml.etree.ElementTree as ET
import datetime
import threading
import mmap
import ffmpeg
from subprocess import PIPE, run
# QA Code
from radon.raw import analyze
from radon.complexity import cc_rank, cc_visit

# Colour blind colours
RED = "#D55F00"# Vermillion
BLUE = "#0072B2"# Blue
# Help Text
HELP = \
"""Controls
p\t\tPlay
s\t\tPause
x\t\tStop
LeftMB\t\tSeek
"""

class Application():
    """Class for Application Window"""
    
    def __init__(self):

        # Create window and set title
        self.root = tk.Tk()
        self.root.title("Brain Data Visualisation Tool")
        self.root.protocol("WM_DELETE_WINDOW",self.quit)# Stop video player before closing

        # Create menubar
        menubar = tk.Menu(tearoff=False)
        self.root.config(menu=menubar)
        filemenu = tk.Menu(menubar,tearoff=False)
        filemenu.add_command(label="Edit Video/fNIRS Sources",command=self.launchImportWindow)
        filemenu.add_command(label="Synchronise Video/fNIRS",command=self.launchSyncToolWindow)
        filemenu.add_command(label="Help",command=self.launchHelpWindow)
        filemenu.add_command(label="Quit",command=self.quit)
        menubar.add_cascade(label="Project",menu=filemenu)
        
        self.dataOffset = 0# Offset at which video is played relative to data
        self.colBlindMode = 1# Colour blind mode
        self.controlLock = threading.Lock()
        self.dataPath = ""
        self.videoPath = ""
        self.data = None # fNIRS data

        self.videoPlayer = VideoPlayer(self.root,self,row=0,column=0)
        self.channelSelector = ChannelSelector(self.root,self,row=0,column=1)
        self.dataPlayers = [DataPlayer(self.root,self,row=1,column=0,sensor_ids=[0,1])]
        for dp in self.dataPlayers:
            self.videoPlayer.dataplayers.append(dp)

    def launchHelpWindow(self):
        """Create a Window to Display Help"""
        self.popup("Help",HELP,geom="350x160")

    def popup(self,title,text,geom="300x100"):
        """Create a Simple Popup"""
        self.w = tk.Toplevel()
        self.w.title(title)
        self.w.geometry(geom)
##        self.w.protocol("WM_DELETE_WINDOW",self.bindHotkeys)
        tk.Label(self.w,text=text,justify=tk.LEFT).grid(row=0,column=0,sticky=tk.NW)
        tk.Button(self.w,text="Ok",command=self.w.destroy).grid(row=1,column=0,sticky=tk.S)
        self.w.mainloop()

    def quit(self):
        """Called when main root closed or quit via menubar"""
        self.unbind()
        self.videoPlayer.stop()
        self.root.destroy()

    def launchImportWindow(self):
        """Launches the Data Importing Interface"""
        self.unbind()
        self.videoPlayer.pause()
        self.w_import = ImportDataWindow(self)

    def launchSyncToolWindow(self):
        """Launches the Sync Tool Window"""
        self.unbind()
        self.videoPlayer.pause()
        self.w_synctool = SyncToolWindow(self)
        
    def reconfigureChannels(self,dataPath,channels):
        """Given dataPath to xml fNIRS file, and a boolean mask (channels),
            destroy and recreate all necessary data players"""
        # Remove references to data players
        self.videoPlayer.dataPlayers = []
        for dp in self.dataPlayers:
            dp.unbind()# Unbind GUI
            dp.c.destroy()# Destroy canvas objects
        self.dataPlayers = []
        i = 0
        while i < len(channels):# For each channel
            sensor_ids = []
            for j in [0,1]:# For Oxy- and Deoxy-Haemoglobin Channels
                if channels[i+j]:# If Channel set to display
                    sensor_ids.append(i+j)
            if len(sensor_ids):# If visible part
                # Create a dataplayer with configured sensors
                self.dataPlayers.append(DataPlayer(self.root,self,row=i+1,column=0,sensor_ids=sensor_ids))
            i += 2
        # Shallow copy array
        self.videoPlayer.dataplayers = self.dataPlayers[:]
        self.loadData(dataPath,resetChannelSelector=False)# Load data into dataplayers
        self.bindDPHotkeys()

    def loadData(self,dataPath,resetChannelSelector=True):
        """Load fNIRS data from path"""
        self.dataPath = dataPath
        self.loadFNIRS(dataPath)
        if resetChannelSelector:
            self.channelSelector.loadData(dataPath)
        for dp in self.dataPlayers:
            dp.loadData()
            dp.draw()

    def loadVideo(self,path,loadAudio=False):
        """Load Video From Path, Use Cached Audio if loadAudio is False"""
        self.videoPlayer.loadVideo(path,loadAudio=loadAudio)
        self.videoPath = path

    def play(self,event=None):
        """Play associated media and data players"""
        if self.controlLock.locked():
            return
        self.controlLock.acquire()
        self.videoPlayer.play()
        self.controlLock.release()

    def pause(self,event=None):
        """"Pause associated media and data players"""
        if self.controlLock.locked():
            return
        self.controlLock.acquire()
        self.videoPlayer.pause()
        self.controlLock.release()
        
    def stop(self,event=None):
        """Stop associated media and data players"""
        if self.controlLock.locked():
            return
        self.controlLock.acquire()
        self.videoPlayer.stop()
        self.controlLock.release()
        
    def zoom(self,event):
        """Zoom in/out on dataplayers with scrollwheel"""
        if self.controlLock.locked():
            return
        self.controlLock.acquire()
        for dp in self.dataPlayers:
            dp.zoom(event.delta*2/120)
        self.controlLock.release()
        
    def skipFor(self,event,t=10):
        """Skip t seconds forward"""
        if self.controlLock.locked():
            return
        self.controlLock.acquire()
        self.videoPlayer.pause()
        self.videoPlayer.seek(self.videoPlayer.progress+t)
        self.videoPlayer.pause()
        self.videoPlayer.play()
        self.controlLock.release()
        
    def bindHotkeys(self):
        """Bind hotkeys to root"""
        self.root.bind("s",self.pause)
        self.root.bind("p",self.play)
        self.root.bind("x",self.stop)
        self.root.bind("<Right>",lambda event, t=10: self.skipFor(event,t=t))
        self.root.bind("<Left>",lambda event, t=-10: self.skipFor(event,t=t))
        self.bindDPHotkeys()

    def unbind(self):
        """Unbind Hotkeys"""
        for k in ["s","p","x","<Right>","<Left>"]:
            self.root.unbind(k)
        for dp in self.dataPlayers:
            dp.unbind()

    def bindDPHotkeys(self):
        """Bind Dataplayer Hotkeys"""
        for dp in self.dataPlayers:
            dp.bindSeek()
            dp.bindZoom()

    def mainloop(self):
        """Hand over control to GUI loop"""
        self.bindHotkeys()
        self.root.mainloop()

    def loadFNIRS(self,filepath):
        """Load fNIRS data from .xml file into app"""
        self.tree = ET.parse(filepath)
        self.data = self.tree.getroot().find("data")
        self.samplerate = float(self.tree.getroot().find('device').find('samplerate').text)
        self.sensors = [i.text for i in self.tree.getroot().find('columns')]
        self.sensorMask = [True]*len(self.sensors)
        self.measurements = len(self.tree.getroot().find('data'))


class ImportDataWindow():
    def __init__(self,app):
        """Create a Window to get Project Data"""
        # Keep Reference to Main Window
        self.app = app
        self.root = tk.Toplevel()
        self.root.grab_set()
        self.root.title("File")
        self.root.geometry("750x200")
        # Create, Grid, and Bind Widgets
        tk.Label(self.root,text="File Path to Video Data: ").grid(row=0,column=0,sticky=tk.NW)
        self.vidPathEntry = tk.Entry(self.root,width=120)
        self.vidPathEntry.grid(row=1,column=0,sticky=tk.NW)
        self.vidPathEntry.insert(tk.END,self.app.videoPath)
        self.loadAudio = tk.IntVar()
        tk.Checkbutton(self.root,text="Use Cached Audio",variable=self.loadAudio).grid(row=2,column=0,sticky=tk.NW)
        tk.Label(self.root,text="File Path to fNIRS (.xml) Data: ").grid(row=3,column=0,sticky=tk.NW)
        self.fnirsPathEntry = tk.Entry(self.root,width=120)
        self.fnirsPathEntry.grid(row=4,column=0,sticky=tk.NW)
        self.fnirsPathEntry.insert(tk.END,self.app.dataPath)
        self.okbtn = tk.Button(self.root,text="Confirm",command=self.onSubmit).grid(row=5,column=0,sticky=tk.NW)
        self.root.protocol("WM_DELETE_WINDOW",self.app.bindHotkeys)
        self.root.mainloop()
    def onSubmit(self):
        """Called when Submit Button is Pressed"""
        vidpath = self.vidPathEntry.get()
        xmlpath = self.fnirsPathEntry.get()
        self.app.dataPath = xmlpath
        self.app.videoPath = vidpath
        self.root.destroy()
        loadAudio = not self.loadAudio.get()
        self.app.loadData(xmlpath)
        self.app.bindHotkeys()
        self.root.grab_release()
        self.app.loadVideo(vidpath,loadAudio=loadAudio)# Invert Boolean

class SyncToolWindow():
    def __init__(self,app):
        """Create a Window for inputting a Video-Data Synchronisation Offset"""
        # Keep Reference to Main Window
        self.app = app
        self.root = tk.Toplevel()
        self.root.grab_set()
        self.root.title("Set Sync Offset")
        self.root.geometry("750x200")
        # Create, Grid, and Bind Widgets
        tk.Label(self.root,text="fNIRS Data Offset (s):").grid(row=0,column=0)
        self.offsetEntry = tk.Entry(self.root)
        self.offsetEntry.grid(row=1,column=0,sticky=tk.NW)
        self.offsetEntry.insert(0,self.app.dataOffset)
        self.errLabel = tk.Label(self.root,fg=RED,text="")
        self.errLabel.grid(row=2,column=0)
        self.colblindFriendly = tk.IntVar()
        colBlindCheck = tk.Checkbutton(self.root,text="Colourblind Mode",variable=self.colblindFriendly)
        colBlindCheck.grid(row=3,column=0,sticky=tk.NW)
        if self.app.colBlindMode:
            colBlindCheck.select()
        self.okbtn = tk.Button(self.root,text="Confirm",command=self.onSubmit).grid(row=4,column=0,sticky=tk.NW)
        self.root.protocol("WM_DELETE_WINDOW",self.app.bindHotkeys)
        self.root.mainloop()
    def onSubmit(self):
        """Called when Submit Button is Pressed"""
        global RED, BLUE
        offset = self.offsetEntry.get()
        try:
            offset = float(offset)
        except:# Display Error for Erroneous Input and Abort
            self.errLabel.config(text="Invalid Input!")
            return
        self.app.dataOffset = offset
        self.root.destroy()
        colblind = self.colblindFriendly.get()
        self.app.colBlindMode = colblind
        if colblind:# Set Colourscheme
            RED = "#D55F00"
            BLUE = "#0072B2"
        else:
            RED = "#ff0000"
            BLUE = "#0000ff"
        # Redraw Dataplayers to Immediately Update Colour Scheme
        for dp in self.app.dataPlayers:
            dp.draw()
        self.app.bindHotkeys()
        self.root.grab_release()

class ChannelSelector():
    """fNIRS Data Channel Selection Widget"""
    ROWS = 16# Number of Checkbuttons Per Column

    def __init__(self,root,app,row=0,column=0):
        """"Initialises the Channel Selector"""
        # tkinter info
        self.root = root
        self.app = app
        # Frame for Layout
        self.frame = tk.Frame(self.root,borderwidth=1,relief=tk.GROOVE)
        self.frame.grid(row=row,column=column,sticky=tk.NW)
        # Checkbutton Widgets
        self.checks = []# tk.Checkbutton instances
        self.intvars = []# tk.IntVar instances
    def loadData(self,filepath):
        """Initialises Checkbuttons with Sensor Names"""
        self.removeCheckbuttons()
        self.tree = ET.parse(filepath)# Parse xml Tree
        self.data = self.tree.getroot().find("data")# Find Data
        self.sensors = [i.text for i in self.tree.getroot().find('columns')]# Get Sensor Names
        for s in self.sensors:# Add Each Sensor as Option
            self.addOption(s)
    def removeCheckbuttons(self):
        """Remove all Checkbuttons"""
        for cb in self.checks:
            cb.destroy()
        self.intvars = []
    def addOption(self,text):
        """Add a Checkbutton and Option to Widget"""
        self.intvars.append(tk.IntVar())
        self.checks.append(tk.Checkbutton(self.frame,text=text,variable=self.intvars[-1],command=self.onClickCheckbutton))
        self.checks[-1].grid(row=(len(self.checks)-1)%self.ROWS,column=(len(self.checks)-1)//self.ROWS,sticky=tk.NW)# Format Neatly
    def onClickCheckbutton(self):
        """Rearrange DataPlayers to New Configuration"""
        self.app.unbind()
        mask = []
        for val in self.intvars:
            mask.append(val.get())
        # Recreate fNIRS Channels with channel mask
        self.app.reconfigureChannels(self.app.dataPath,mask)
        self.app.bindHotkeys()

class DataPlayer():
    """fNIRS Data Player Widget"""

    def __init__(self,root,app,row=0,column=0,width=1000,height=100,sensor_ids=[4,5]):
        """Initialises data player"""

        # tkinter info
        self.root = root
        self.app = app
        self.w,self.h = width,height
        
        # Create canvas widget
        self.c = tk.Canvas(self.root,width=self.w,height=self.h,bg='#ffffff')
        self.c.grid(row=row,column=column,sticky=tk.NW,columnspan=100)

        # Start and end of x scale (seconds)
        self.scalex = [0,1]
        # Height of each data track
        self.scaley = [-10,10]
        self.scaleLock = threading.Lock()

        # Member variables associate to currently loaded xml file
        self.samplerate = 1# Device Sample Rate (Hz)
        self.sensors = None# List of sensor names
        self.sensorMask = None# Boolean mask for which sensors outputs to draw
        self.measurements = None# Number of measurements
        self.sensor_ids = sensor_ids# Sensors to display in this data player
        self.sensor_range = [0,1]# Range of lowest to highest sensor readings

        # Scrubber Visualisation
        self.scrubber = []
        self.progress = 0# Keep track of current dataplayer timestamp when paused
        self.drawScrubber()

    def clear(self):
        """Clean canvas"""
        self.c.delete(tk.ALL)
        self.scrubber = []

    def zoom(self,factor):
        """Zoom in/out of dataplayer"""
        # Set x axis range
        self.scaleLock.acquire()
        scalex = self.scalex[:]# Copy zoom
        self.scaleLock.release()
        range_ = scalex[1] - scalex[0]
        scalex[0] += range_*factor/10
        scalex[1] -= range_*factor/10
        # Centre range around scrubber
        range_ = scalex[1] - scalex[0]
        if range_ < self.w//2 and factor > 0:
            range_ = self.w//2
        if self.measurements is not None and range_ > self.measurements*2 and factor < 0:
            range_ = self.measurements*2
        scalex[0] = self.progress*self.samplerate - range_/2
        scalex[1] = self.progress*self.samplerate + range_/2
        self.scaleLock.acquire()
        self.scalex = scalex[:]
        self.scaleLock.release()
        
        self.draw()
        self.update(self.app.videoPlayer.startTimestamp)

    def plot(self,x,y):
        """Transform data to pixel coordinates"""
        scalex,scaley = self.scalex[:],self.scaley[:]
        x = x*self.samplerate
        x = (x-scalex[0])/(scalex[1]-scalex[0])*self.w
        y = (y-scaley[0])/(scaley[1]-scaley[0])*self.h
        return (x,y)

    def drawScrubber(self):
        """Draw scrubber at progress location"""
        x = self.plot(self.progress,0)[0]
        if self.scrubber != []:
            for cid in self.scrubber:
                self.c.delete(cid)
        self.scrubber = [self.c.create_rectangle(x-3,0,x+3,6,fill="#000000",tags=("scrubber"))]# Scrubber head
        self.scrubber.append(self.c.create_line(x,0,x,self.h,fill="#000000",tags=("scrubber")))# Scrubber line
        t = "-"*(self.progress<0) +str(datetime.timedelta(seconds=abs(round(self.progress))))
        self.scrubber.append(self.c.create_text(x+3,0,text=str(t),anchor=tk.NW,tags=("scrubber")))# Timestamp
        if self.progress > 0:
            self.scrubber.append(self.c.create_text(x+3,10,text=str(self.getData(self.sensor_ids[0],self.progress)),fill=RED,anchor=tk.NW,tags=("scrubber")))# Red track value
            if len(self.sensor_ids) == 2:# If blue track exists
                self.scrubber.append(self.c.create_text(x+3,20,text=str(self.getData(self.sensor_ids[1],self.progress)),fill=BLUE,anchor=tk.NW,tags=("scrubber")))# Blue track value
        
    def update(self,startTime):
        """Get updates from the video player"""
        # Calculate elapsed time
        now = time.time()
        elapsedTime = now-startTime+self.app.dataOffset
        if self.app.videoPlayer.state == VideoPlayer.State.PLAYING:
            self.progress = elapsedTime

        # Move the scrubber to the right place
        timespan = 1/self.samplerate * (self.scalex[1]-self.scalex[0])# Time represented by canvas width, in seconds
        scalex_secs = [self.scalex[0]/self.samplerate,self.scalex[1]/self.samplerate]# Start and end of plot, in seconds
        x = ((elapsedTime-scalex_secs[0])/(scalex_secs[1]-scalex_secs[0]))*self.w
        self.drawScrubber()

        # If out of bounds
        if x < 0:# Set canvas x range to 0
            self.scalex[1] -= self.scalex[0]
            self.scalex[0] = 0
            self.draw()# Draw starting strip
        if x > self.w:# Set canvas x range to proceed
            range_ = self.scalex[1] - self.scalex[0]
            self.scalex[0] += range_*x/self.w
            self.scalex[1] += range_*x/self.w
            self.draw()# Draw next strip
            
        # Update the canvas
        self.c.update()

    def seek(self,event):
        """Seek to where the user clicked"""
        if self.app.controlLock.locked():
            return
        self.app.controlLock.acquire()
        x = event.x
        scalex_secs = [self.scalex[0]/self.samplerate,self.scalex[1]/self.samplerate]# Get x scale in seconds
        seekTo = (x/self.w) * (scalex_secs[1]-scalex_secs[0]) + scalex_secs[0]# Transform pixel coordinates to represented time
        self.app.videoPlayer.pause()
        self.app.videoPlayer.seek(seekTo-self.app.dataOffset)
        self.app.videoPlayer.pause()# Restart audio to sync
        self.update(self.app.videoPlayer.startTimestamp)
        self.draw()
        self.app.videoPlayer.play()
        self.app.controlLock.release()

    def bindSeek(self):
        """Bind button press on this widget to seeking behaviour"""
        self.c.bind("<Button-1>",self.seek)

    def bindZoom(self):
        """Bind button press on this widget to zoom behaviour (via app class)"""
        self.c.bind("<MouseWheel>",self.app.zoom)

    def unbind(self):
        self.c.unbind("<Button-1>")
        self.c.unbind("<MouseWheel>")

    def setScaleX(self,startx,endx):
        """Set x scale to list"""
        self.scalex = [startx,endx]
        # Redraw
        self.draw()
        
    def setScaleY(self,starty,endy):
        """Set y scale, one number representing the max value either side of 0"""
        self.scaley = [starty,endy]

    def loadData(self):
        """Update dataplayer with data stored in app"""
        self.samplerate = self.app.samplerate
        self.sensors = self.app.sensors
        self.sensorMask = self.app.sensorMask
        self.measurements = self.app.measurements

        # Get min and max data points
        for sens in self.sensor_ids:
            for i in range(1,self.measurements):
                if float(self.app.data[i][sens].text) < self.sensor_range[0]:
                    self.sensor_range[0] = float(self.app.data[i][sens].text)
                elif float(self.app.data[i][sens].text) > self.sensor_range[1]:
                    self.sensor_range[1] = float(self.app.data[i][sens].text)
        
        # Set x scale from 0 to end of track
        self.scalex = [0,self.measurements]
##        self.scalex = [0,self.w/2]
        # Set y scale to maximum sensor measurement
        self.setScaleY(self.sensor_range[0], self.sensor_range[1])
    def getData(self,sensor_id,t):
        """Get data from sensor at time t"""
        try:
            return round(float(self.app.data[int(t*self.samplerate)][sensor_id].text),3)
        except:# No data loaded, or scrubber out of bounds
            return 0
    def drawLayout(self):
        """Draw the Graph Axis and Labels, with respect to fNIRS metadata and zoom"""
        # Display sensor names
        self.c.create_text(30,20,text=self.sensors[self.sensor_ids[0]],fill=RED,anchor=tk.NW)
        if len(self.sensor_ids) == 2:# If displaying blue sensor
            self.c.create_text(30,40,text=self.sensors[self.sensor_ids[1]],fill=BLUE,anchor=tk.NW)
        # Draw Border -
        for coords in [[2,2,self.w,2],[2,self.h,self.w,self.h],[2,2,2,self.h],[self.w,2,self.w,self.h]]:
            self.c.create_rectangle(coords[0],coords[1],coords[2],coords[3],fill="#000000",width=2)
##        self.c.create_rectangle(2,2,self.w,self.h,fill="",outline="#000000",width=2)
        # Draw X Axis
        y0 = ((-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
        self.c.create_line(0,-y0+self.h,self.w,-y0+self.h,fill="#bebebe",width=2)
        # Draw Y Axis Labels
        self.c.create_text(5,5,text=str(self.scaley[1]),fill="#000000",anchor=tk.NW)
        self.c.create_text(5,self.h-15,text=str(self.scaley[0]),fill="#000000",anchor=tk.SW)
        self.c.create_text(self.w-5,self.h-5,text=str(datetime.timedelta(seconds=round(self.scalex[1]/self.samplerate))),fill="#000000",anchor=tk.SE)
        # Draw X Axis Labels
        time_start = str(datetime.timedelta(seconds=abs(round(self.scalex[0]/self.samplerate))))
        if self.scalex[0] < 0:# Format correctly
            time_start = "-"+time_start
        self.c.create_text(15,self.h-5,text=time_start,fill="#000000",anchor=tk.SW)
    def draw(self):
        """Draw braindata to canvas, with respect to fNIRS metadata and zoom"""
        try:
            self.clear()
            if self.app.data == None:# If no data, break
                return
            # How much each pixel represents
            if self.scalex[1]-self.scalex[0] == 0:
                return
            step = (self.scalex[1]-self.scalex[0])/self.w# Draw lines at pixel level resolution
            # Draw Graph Background
            self.drawLayout()
            sens_index = [0]# If one sensor displayed in this data player
            if len(self.sensor_ids) == 2:# If two sensors displayed in this data player
                sens_index = [1,0]# Draw order blue then red to make blue line on top
            for s in sens_index:
                i = self.scalex[0]
                x = 0
                while i < self.scalex[1]:
                    i += step# i Is data
                    x += 1# x is iteration/pixel-coordinate
                    if i<0:# Skip data for t<0
                        continue
                    try:
                        # Data retrieved from xml
                        y = float(self.app.data[int(i)][self.sensor_ids[s]].text)
                        y2 = float(self.app.data[int(i+step)][self.sensor_ids[s]].text)
                        # Normalize into range 0 to 1 and multiply by height
                        y = ((y-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
                        y2 = ((y2-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
                    except IndexError:# Missing data is skipped
                        continue
                    self.c.create_line(x,-y+self.h,x+1,-y2+self.h,fill=[RED,BLUE][s],width=2)
            self.drawScrubber()
            self.c.update()
        except tk.TclError:# If canvas destroyed, cancel draw operation
            return
        


class VideoPlayer():
    """Video Player Widget"""

    class State(Enum):
        """Nested Inner Class for Video Player States"""
        PLAYING = 1
        PAUSED = 2
        STOPPED = 0
        EMPTY = -1# No Associated Video Track
    
    def __init__(self,root,app,row=0,column=0,w=640,h=400):
        """Initialises video player into root"""
        self.app = app
        # Create Label to stream video into
        self.root = root
        self.player = tk.Label(root,bg='#000000')
        self.player.grid(row=row,column=column,sticky=tk.NW)
        self.startTimestamp = 0# Timestamp when video started (so correct frame is drawn)
        mixer.init()

        # Video Player Width And Height
        self.w,self.h = w,h

        # State
        self.state = VideoPlayer.State.EMPTY
        self.progress = 0
        self.hasAudio = False
        
        # Video
        self.vid_path = ""
        self.aud_path = ""
        self.vid = None
        self.vid_len = 0

        # Linked DataPlayers
        self.dataplayers = []

        # Black Frame
        self.setBlackFrame()
    # For comparing states
    def isPlaying(self):
        return self.state == VideoPlayer.State.PLAYING
    def isPaused(self):
        return self.state == VideoPlayer.State.PAUSED
    def isStopped(self):
        return self.state == VideoPlayer.State.STOPPED
    def isEmpty(self):
        return self.state == VideoPlayer.State.EMPTY
    def loadAudio(self,path):
        """Extract Audio From File, Save as MP3, Load"""
        if self.vid:# Release video to access
            self.vid.release()
        # Check if has audio
        mixer.music.unload()
        command = "ffprobe -i \"{0}\" -show_streams -select_streams a -loglevel error".format(path)
        result = run(command,stdout=PIPE,stderr=PIPE,universal_newlines=True,shell=True)
        if result.stdout.startswith("[STREAM]"):# Contains audio
            self.hasAudio = True
        else:
            self.hasAudio = False
            return
        print("Preparing Audio...",end="")
        filename = "project_audio.mp3"
        self.aud_path = filename
        t_start = time.time()
        # Extract audio using ffmpeg, always overwrite
        command = "ffmpeg -y -i \"{0}\" \"{1}\"".format(path,filename)
        result = run(command,stdout=PIPE,stderr=PIPE,universal_newlines=True,shell=True)
##        print(result.stderr)
        t_end = time.time()
        print("Done[{0}]".format(int(t_end-t_start)))
        try:
            mixer.music.unload()
            mixer.music.load(filename)
        except:
            print("Error Loading Audio")
            self.hasAudio = False
        self.vid = cv2.VideoCapture(self.vid_path)# Reload video component
        self.app.popup("Audio Importer","Audio Import Complete")
    def loadCachedAudio(self):
        """Unstable, for testing purposes only"""
        self.aud_path = "project_audio.mp3"
        mixer.music.unload()
        print("Loading Cached Audio...")
        try:
            mixer.music.load("project_audio.mp3")
        except:
            print("Error Loading Cached Audio")
            mixer.music.unload()
            self.aud_path = None
            self.hasAudio = False

    def loadVideo(self,path,loadAudio=True):
        """Select a video for the player, if loadAudio is False it will use the cached audio"""
        self.aud_path = ""
        # Get cv2 video capture object
        self.vid_path = path
        self.vid = cv2.VideoCapture(self.vid_path)
        self.delay = int(1000/self.vid.get(cv2.CAP_PROP_FPS))
        self.vid_len = int(self.vid.get(cv2.CAP_PROP_FRAME_COUNT))/self.vid.get(cv2.CAP_PROP_FPS)
        self.state = VideoPlayer.State.STOPPED
        self.hasAudio = True# If no audio in video, ignore audio
        if loadAudio:
            self.loadAudio(self.vid_path)
        else:
            self.loadCachedAudio()

    def updateDataplayers(self):
        """Update subscribed dataplayer objects"""
        try:
            for dp in self.dataplayers:
                dp.update(self.startTimestamp)
        except tk.TclError:# If dataplayers are destroyed, pass
            pass

    def play(self,event=None):
        """Causes the media to play, or resume playing"""
        # If play -> play, ignore or if no video data
        if self.isPlaying() or self.isEmpty():
            return
        # If stop -> play, restart clip
        elif self.isStopped():
            if self.hasAudio:
                mixer.music.play(loops=0)
            self.startTimestamp = time.time()
        # If pause -> play, set progress and resume
        elif self.isPaused():
            if self.hasAudio:
                mixer.music.unload()
                mixer.music.load(self.aud_path)
            self.seek(self.progress)
            return
        self.state = VideoPlayer.State.PLAYING
        self.root.after(0,self.stream)

    def seek(self,t):
        """Seek to time t and play"""
        if (t > self.vid_len) or (t < 0):# If seeking to beyond end of video
            frame = ImageTk.PhotoImage(Image.fromarray(np.array([[0]*self.w]*self.h)))# Set frame to a black image of same proportions
            self.player.config(image=frame)
            self.player.image = frame
            self.root.update_idletasks()
        self.startTimestamp = time.time() - t
        if self.hasAudio:
            mixer.music.play(start=t,loops=0)
        self.updateDataplayers()
        # If already playing, skip calling the stream method, or if no video data loaded
        if self.isPlaying() or self.isEmpty():
            return
        self.state = VideoPlayer.State.PLAYING
        self.root.after(0,self.stream)

    def pause(self,event=None):
        """Pause video and audio"""
        # If pause -> pause or stop -> pause, ignore, or if no video
        if not self.isPlaying():
            return
        # If play -> pause
        self.progress = time.time() - self.startTimestamp
        if self.hasAudio:
            mixer.music.pause()
        self.state = VideoPlayer.State.PAUSED

    def stop(self,event=None):
        """Stop video and audio"""
        # If no video data
        if self.isEmpty():
            return
        if self.hasAudio:
            mixer.music.stop()
        self.state = VideoPlayer.State.STOPPED

    def setBlackFrame(self):
        """Sets Widget to Display a Black Frame with Default Proportions"""
        frame = ImageTk.PhotoImage(Image.fromarray(np.array([[0]*self.w]*self.h)))
        self.player.config(image=frame)
        self.player.image = frame

    def stream(self,event=None):
        """Start a video update loop"""

        if not self.isPlaying():# If not playing, return
            return

        # Calculate elapsed time
        seconds = time.time() - self.startTimestamp

        if seconds < 0:
            if mixer.music.get_busy():
                mixer.music.pause()
        elif seconds < self.vid_len:
            if not mixer.music.get_busy() and self.hasAudio:
                mixer.music.play()
                self.play()
        
        # Set frame number
        self.vid.set(cv2.CAP_PROP_POS_MSEC,seconds*1000)

        # Get next frame
        succ, image = self.vid.read()
        if not succ:
            frame = ImageTk.PhotoImage(Image.fromarray(np.array([[0]*self.w]*self.h)))
        else:
            # Frame processing pipeline
            image = cv2.resize(image, dsize=(self.w,self.h))
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            frame = ImageTk.PhotoImage(Image.fromarray(image))

        # Set label image to frame
        self.player.config(image=frame)
        self.player.image = frame
        self.root.update_idletasks()

        self.updateDataplayers()

        # Display next frame after delay
        self.player.after(self.delay//2, self.stream)# self.delay, or 0 for best video framerate


def qa_test():
    """Quality Assurance Logging Subroutine"""
    # Reads Code and Runs Code Metrics
    with open("BrainDataVisualiser.py","r") as file:
        code = file.read()
    with open("QA_LOGS.txt","a") as file:
        # Timestamp and append metric results to log
        file.write(datetime.date.today().strftime("%b-%d-%Y")+"\n\t")
        file.write("General Analysis\n\t\t")
        file.write(str(analyze(code))+"\n\t")
        file.write("Cyclomatic Complexity\n")
        for i in cc_visit(code):
            file.write("\t\t"+cc_rank(i.complexity)+" "+str(i)+"\n")

# For Testing
THERMAL = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Julian_Max_project\\P_09\\Thermal\\P_09_thermal.wmv"
VISUAL = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Julian_Max_project\\P_09\\Visual\\converted\\M2U00010.mp4"
#C:\Users\hench\OneDrive - The University of Nottingham\Julian_Max_project\P_09\Thermal\P_09_thermal.wmv
#C:\Users\hench\OneDrive - The University of Nottingham\Julian_Max_project\P_09\Visual\converted\M2U00010.mp4

vid_path = VISUAL
data_path = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Modules\\Dissertation\\braindata.xml"
#C:\Users\hench\OneDrive - The University of Nottingham\Modules\Dissertation\braindata.xml

qa_test()

app = Application()
#audio = (for debugging)
audio = app.loadVideo(vid_path,loadAudio=False)
app.loadData(data_path)
app.reconfigureChannels(data_path,[True]*4)
app.play()
##app.reconfigureChannels(data_path,[True,True,False])
app.mainloop()
# Release video if used
if app.videoPlayer.vid != None:
    app.videoPlayer.vid.release()
