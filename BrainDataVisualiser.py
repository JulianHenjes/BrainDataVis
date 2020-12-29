# Python 3.6.2, 64-bit
# Dependencies:
# imageio
# imageio_ffmpeg
# pillow
# cv2
# numpy
# pygame
# radon

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
# QA Code
from radon.raw import analyze
from radon.complexity import cc_rank, cc_visit

# Colour blind colours
RED = "#D55F00"# Vermillion
BLUE = "#0072B2"# Blue

class Application():
    """Class for Application Window"""
    
    def __init__(self):

        # Create window and set title
        self.root = tk.Tk()
        self.root.title("Brain Data Visualisation Tool")

        self.dataOffset = 0# Offset at which video is played relative to data
        self.controlLock = threading.Lock()
        self.data_path = None

        self.videoPlayer = VideoPlayer(self.root,self,row=0,column=0)
        self.dataPlayers = [DataPlayer(self.root,self,row=1,column=0,sensor_ids=[0,1])]
        for dp in self.dataPlayers:
            self.videoPlayer.dataplayers.append(dp)

    def reconfigureChannels(self,data_path,channels):
        """Given data_path to xml fNIRS file, and a boolean mask (channels),
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
            if channels[i]:# If visible flag set to true
                # Create a dataplayer with configured sensors
                self.dataPlayers.append(DataPlayer(self.root,self,row=i+1,column=0,sensor_ids=[i,i+1]))
                i += 2# TODO
        # Shallow copy array
        self.videoPlayer.dataplayers = self.dataPlayers[:]
        self.loadData(data_path)# Load data into dataplayers

    def loadData(self,data_path):
        """Load fNIRS data from path"""
        self.data_path = data_path
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

    def __init__(self,root,app,row=0,column=0,width=1000,height=100,sensor_ids=[4,5]):
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
    def drawLayout(self):
        """Draw the Graph Axis and Labels, with respect to fNIRS metadata and zoom"""
        # Display sensor names
        self.c.create_text(30,20,text=self.sensors[self.sensor_ids[0]],fill=RED,anchor=tk.NW)
        if len(self.sensor_ids) == 2:# If displaying blue sensor
            self.c.create_text(30,40,text=self.sensors[self.sensor_ids[1]],fill=BLUE,anchor=tk.NW)
        # Draw Border
        self.c.create_rectangle(2,2,self.w,self.h,fill="",outline="#000000",width=2)
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
        self.clear()
        if self.data == None:# If no data, break
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
                    y = float(self.data[int(i)][self.sensor_ids[s]].text)
                    y2 = float(self.data[int(i+step)][self.sensor_ids[s]].text)
                    # Normalize into range 0 to 1 and multiply by height
                    y = ((y-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
                    y2 = ((y2-self.scaley[0])/(self.scaley[1]-self.scaley[0])) * self.h
                except IndexError:# Missing data is skipped
                    continue
                self.c.create_line(x,-y+self.h,x+1,-y2+self.h,fill=[RED,BLUE][s],width=2)
        self.drawScrubber()
        self.c.update()
        


class VideoPlayer():
    """Class for Video Player Widget"""

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
        self.vid = None
        self.vid_len = 0

        # Linked DataPlayers
        self.dataplayers = []

        # Black Frame
        self.setBlackFrame()

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
        self.hasAudio = True
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
        self.state = VideoPlayer.State.STOPPED

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
        if self.state == VideoPlayer.State.PLAYING or self.state == VideoPlayer.State.EMPTY:
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
        # If already playing, skip calling the stream method, or if no video data loaded
        if self.state == self.state.PLAYING or self.state == self.state.EMPTY:
            return
        self.state = VideoPlayer.State.PLAYING
        self.root.after(0,self.stream)

    def pause(self,event=None):
        """Pause video and audio"""
        # If pause -> pause or stop -> pause, ignore, or if no video
        if self.state != VideoPlayer.State.PLAYING:
            return
        # If play -> pause
        self.progress = time.time() - self.startTimestamp
        if self.hasAudio:
            mixer.music.pause()
        self.state = VideoPlayer.State.PAUSED

    def stop(self,event=None):
        """Stop video and audio"""
        # If no video data
        if self.state == VideoPlayer.State.EMPTY:
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

        if self.state != VideoPlayer.State.PLAYING:# If not playing, return
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


vid_path = VISUAL
data_path = "C:\\Users\\hench\\OneDrive - The University of Nottingham\\Modules\\Dissertation\\braindata.xml"

##qa_test()

app = Application()
#audio = (for debugging)
##audio = app.videoPlayer.loadVideo(vid_path,loadAudio=False)
app.loadData(data_path)
app.reconfigureChannels(data_path,[True]*4)
##app.play()
##app.reconfigureChannels(data_path,[True,True,False])
app.mainloop()
# Release video if used
if app.videoPlayer.vid != None:
    app.videoPlayer.vid.release()
