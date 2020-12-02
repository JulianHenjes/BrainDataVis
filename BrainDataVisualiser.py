# Python 3.6.2, 64-bit
# Dependencies:
# imageio
# imageio_ffmpeg
# pillow
# cv2
# numpy
# pygame

import tkinter as tk
from PIL import ImageTk, Image
import cv2
import numpy as np
from moviepy.editor import VideoFileClip
import os
import threading
import time
import pygame.mixer as mixer
from enum import Enum
import xml.etree.ElementTree as ET
import datetime
import threading


class Application():
    """Class for Application Window"""
    
    def __init__(self):

        # Create window and set title
        self.root = tk.Tk()
        self.root.title("Brain Data Visualisation Tool")

        self.dataOffset = 0# Offset at which video is played relative to data
        self.controlLock = threading.Lock()

        self.videoPlayer = VideoPlayer(self.root,self,row=0,column=0)
        self.dataPlayers = [DataPlayer(self.root,self,row=1,column=0)]
        for dp in self.dataPlayers:
            self.videoPlayer.dataplayers.append(dp)

    def loadData(self,data_path):
        """Load fNIRS data from path"""
        for dp in self.dataPlayers:
            dp.loadData(data_path)
            dp.draw()

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
        for dp in self.dataPlayers:
            dp.bindSeek()
            dp.bindZoom()

    def mainloop(self):
        """Hand over control to GUI loop"""
        self.bindHotkeys()
        self.root.mainloop()



class DataPlayer():

    def __init__(self,root,app,row=0,column=0,width=700,height=200):
        """Initialises data player"""

        # tkinter info
        self.root = root
        self.app = app
        self.w,self.h = width,height
        
        # Create canvas widget
        self.c = tk.Canvas(self.root,width=self.w,height=self.h,bg='#ffffff')
        self.c.grid(row=row,column=column,sticky=tk.NW)

        # Start and end of x scale (seconds)
        self.scalex = [0,1]
        # Height of each data track
        self.scaley = [-10,10]
        self.scaleLock = threading.Lock()

        # Member variables associate to currently loaded xml file
        self.data = None# fNIRS xml data
        self.samplerate = 1# Device Sample Rate (Hz)
        self.sensors = None# List of sensor names
        self.sensorMask = None# Boolean mask for which sensors outputs to draw
        self.measurements = None# Number of measurements
        self.sensor_ids = [4,5]# Sensors to display in this data player
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
        if range_ > self.measurements*2 and factor < 0:
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
            self.scrubber.append(self.c.create_text(x+3,10,text=str(self.getData(self.sensor_ids[0],self.progress)),fill="#ff0000",anchor=tk.NW,tags=("scrubber")))# Red track value
            self.scrubber.append(self.c.create_text(x+3,20,text=str(self.getData(self.sensor_ids[1],self.progress)),fill="#0000ff",anchor=tk.NW,tags=("scrubber")))# Blue track value
        
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
            self.scalex[0] += range_
            self.scalex[1] += range_
            self.draw()# Draw next strip
            
        # Update the canvas
        self.c.update()

    def seek(self,event):
        """Seek to where the user clicked"""
        x = event.x
        scalex_secs = [self.scalex[0]/self.samplerate,self.scalex[1]/self.samplerate]# Get x scale in seconds
        seekTo = (x/self.w) * (scalex_secs[1]-scalex_secs[0]) + scalex_secs[0]# Transform pixel coordinates to represented time
        self.app.videoPlayer.pause()
        self.app.videoPlayer.seek(seekTo-self.app.dataOffset)
        self.app.videoPlayer.pause()# Restart audio to sync
        self.update(self.app.videoPlayer.startTimestamp)
        self.draw()
        self.app.videoPlayer.play()

    def bindSeek(self):
        """Bind button press on this widget to seeking behaviour"""
        self.c.bind("<Button-1>",self.seek)

    def bindZoom(self):
        """Bind button press on this widget to zoom behaviour (via app class)"""
        self.c.bind("<MouseWheel>",self.app.zoom)

    def setScaleX(self,startx,endx):
        """Set x scale to list"""
        self.scalex = [startx,endx]
        # Redraw
        self.draw()
        
    def setScaleY(self,starty,endy):
        """Set y scale, one number representing the max value either side of 0"""
        self.scaley = [starty,endy]

    def loadData(self,filepath):
        """Load fNIRS data from .xml file"""
        self.tree = ET.parse(filepath)
        self.data = self.tree.getroot().find("data")
        #self.data[ <sample> ][ <sensor_num> ]
        
        self.samplerate = float(self.tree.getroot().find('device').find('samplerate').text)
        self.sensors = [i.text for i in self.tree.getroot().find('columns')]
        self.sensorMask = [True]*len(self.sensors)
        self.measurements = len(self.tree.getroot().find('data'))

        # Get min and max data points
        for sens in self.sensor_ids:
            for i in range(1,self.measurements):
                if float(self.data[i][sens].text) < self.sensor_range[0]:
                    self.sensor_range[0] = float(self.data[i][sens].text)
                elif float(self.data[i][sens].text) > self.sensor_range[1]:
                    self.sensor_range[1] = float(self.data[i][sens].text)
        # Set x scale from 0 to end of track
##        self.scalex = [0,self.measurements]
        self.scalex = [0,self.w/2]
        # Set y scale to maximum sensor measurement
        self.setScaleY(self.sensor_range[0], self.sensor_range[1])
    def getData(self,sensor_id,t):
        """Get data from sensor at time t"""
        try:
            return round(float(self.data[int(t*self.samplerate)][sensor_id].text),3)
        except:# No data loaded, or scrubber out of bounds
            return 0
    def draw(self):
        self.clear()
        """Draw braindata to canvas, according to fNIRS metadata and zoom level"""
        if self.data == None:
            return
        # How much each pixel represents
        if self.scalex[1]-self.scalex[0] == 0:
            return
        step = (self.scalex[1]-self.scalex[0])/self.w
        # Draw x axis
        y0 = ((-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
        self.c.create_line(0,-y0+self.h,self.w,-y0+self.h,fill="#bebebe",width=2)
        # Draw lines at pixel level resolution
        self.c.create_text(30,20,text=self.sensors[self.sensor_ids[0]],fill="#ff0000",anchor=tk.NW)
        self.c.create_text(30,40,text=self.sensors[self.sensor_ids[1]],fill="#0000ff",anchor=tk.NW)
        # Draw axis labels
        self.c.create_text(5,5,text=str(self.scaley[1]),fill="#000000",anchor=tk.NW)
        self.c.create_text(5,self.h-15,text=str(self.scaley[0]),fill="#000000",anchor=tk.SW)
        self.c.create_text(self.w-5,self.h-5,text=str(datetime.timedelta(seconds=round(self.scalex[1]/self.samplerate))),fill="#000000",anchor=tk.SE)
        time_start = str(datetime.timedelta(seconds=abs(round(self.scalex[0]/self.samplerate))))
        if self.scalex[0] < 0:# Format correctly
            time_start = "-"+time_start
        self.c.create_text(15,self.h-5,text=time_start,fill="#000000",anchor=tk.SW)
        for s in [1,0]:# Draw red over blue
            i = self.scalex[0]
            x = 0
            while i < self.scalex[1]:
                i += step# i Is data
                x += 1# x is iteration/pixel-coordinate
                if i<0:# Skip data for t<0
                    continue
                try:
                    # Data retrieved from xml
                    y = float(self.data[int(i)][self.sensor_ids[s]].text)
                    y2 = float(self.data[int(i+step)][self.sensor_ids[s]].text)
                    # Normalize into range 0 to 1 and multiply by height
                    y = ((y-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
                    y2 = ((y2-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
                except IndexError:# Missing data is skipped
                    continue
                self.c.create_line(x,-y+self.h,x+1,-y2+self.h,fill=["#ff0000","#0000ff"][s],width=2)
        self.drawScrubber()
        self.c.update()
        


class VideoPlayer():
    """Class for Video Player Widget"""

    class State(Enum):
        """Nested Inner Class for Video Player States"""
        PLAYING = 1
        PAUSED = 2
        STOPPED = 0
    
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
        self.state = VideoPlayer.State.STOPPED
        self.progress = 0
        self.hasAudio = True
        
        # Video
        self.vid_path = ""
        self.vid = None
        self.vid_len = 0

        # Linked DataPlayers
        self.dataplayers = []

    def loadVideo(self,path,loadAudio=True):
        """Select a video for the player, if loadAudio is False it will use the cached audio"""
        # Get cv2 video capture object
        self.vid_path = path
        self.vid = cv2.VideoCapture(self.vid_path)
        self.delay = int(1000/self.vid.get(cv2.CAP_PROP_FPS))
        self.hasAudio = True# If no audio in video, ignore audio
        self.vid_len = int(self.vid.get(cv2.CAP_PROP_FRAME_COUNT))/self.vid.get(cv2.CAP_PROP_FPS)

        # Separate audio and save
        audio = VideoFileClip(self.vid_path).audio
        if audio == None:
            self.hasAudio = False
            return

        if loadAudio:
            print("Preparing Audio...",end="")
            t_start = time.time()
            audio.write_audiofile("project_audio.mp3",verbose=False,logger=None)
            t_end = time.time()
            print("Done [",int(t_end-t_start),"]",sep="")
        mixer.music.load("project_audio.mp3")

    def updateDataplayers(self):
        """Update subscribed dataplayer objects"""
        for dp in self.dataplayers:
            dp.update(self.startTimestamp)

    def play(self,event=None):
        """Causes the media to play, or resume playing"""
        # If play -> play, ignore
        if self.state == VideoPlayer.State.PLAYING:
            return
        # If stop -> play, restart clip
        elif self.state == VideoPlayer.State.STOPPED:
            if self.hasAudio:
                mixer.music.play(loops=0)
            self.startTimestamp = time.time()
        # If pause -> play, set progress and resume
        elif self.state == VideoPlayer.State.PAUSED:
            if self.hasAudio:
                mixer.music.load("project_audio.mp3")
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
        # If already playing, skip calling the stream method
        if self.state == self.state.PLAYING:
            return
        self.state = VideoPlayer.State.PLAYING
        self.root.after(0,self.stream)

    def pause(self,event=None):
        """Pause video and audio"""
        # If pause -> pause or stop -> pause, ignore
        if self.state != VideoPlayer.State.PLAYING:
            return
        # If play -> pause
        self.progress = time.time() - self.startTimestamp
        if self.hasAudio:
            mixer.music.pause()
        self.state = VideoPlayer.State.PAUSED

    def stop(self,event=None):
        """Stop video and audio"""
        if self.hasAudio:
            mixer.music.stop()
        self.state = VideoPlayer.State.STOPPED

    def stream(self,event=None):
        """Start a video update loop"""

        if self.state != VideoPlayer.State.PLAYING:
            return

        # Calculate elapsed time
        seconds = time.time() - self.startTimestamp

        if seconds < 0:
            if mixer.music.get_busy():
                mixer.music.pause()
        elif seconds < self.vid_len:
            if not mixer.music.get_busy():
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
        self.player.after(self.delay//2, self.stream)# self.delay, or 0 for best framerate


# For Testing
THERMAL = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Julian_Max_project\\P_09\\Thermal\\P_09_thermal.wmv"
VISUAL = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Julian_Max_project\\P_09\\Visual\\converted\\M2U00010.mp4"


vid_path = VISUAL
data_path = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Modules\\Dissertation\\braindata.xml"

app = Application()
audio = app.videoPlayer.loadVideo(vid_path,loadAudio=False)
app.loadData(data_path)
app.play()
app.mainloop()
app.videoPlayer.vid.release()
