# Copyright (C) 2009-2011 AG Projects. See LICENSE for details.
#

import datetime
import time

from objc import YES, NO, IBAction, IBOutlet
from AppKit import *
from Foundation import *

from application.notification import IObserver, NotificationCenter
from application.python import Null
from zope.interface import implements
from util import *

from MediaStream import *

ice_candidates= {'srflx': 'Server Reflexive',
                 'prflx': 'Peer Reflexive',
                 'host': 'Host',
                 'relay': 'Server Relay'
                 }

class SessionInfoController(NSObject):
    implements(IObserver)

    window = objc.IBOutlet()

    sessionBox = objc.IBOutlet()
    audioBox = objc.IBOutlet()
    chatBox = objc.IBOutlet()
     
    remote_party = objc.IBOutlet()
    duration = objc.IBOutlet()
    remote_ua = objc.IBOutlet()
    status = objc.IBOutlet()
    conference = objc.IBOutlet()
    remote_endpoint = objc.IBOutlet()
    local_endpoint = objc.IBOutlet()
    tls_lock = objc.IBOutlet()

    audio_status = objc.IBOutlet()
    audio_srtp_active = objc.IBOutlet()
    audio_codec = objc.IBOutlet()
    audio_sample_rate = objc.IBOutlet()
    audio_local_endpoint = objc.IBOutlet()
    audio_remote_endpoint = objc.IBOutlet()
    audio_ice_negotiation = objc.IBOutlet()
    audio_ice_local_candidate = objc.IBOutlet()
    audio_ice_remote_candidate = objc.IBOutlet()
    audio_rtt = objc.IBOutlet()
    audio_packet_loss = objc.IBOutlet()
    audio_rtt_graph = objc.IBOutlet()
    audio_packet_loss_graph = objc.IBOutlet()
    audio_jitter = objc.IBOutlet()
    audio_jitter_graph = objc.IBOutlet()
    audio_srtp_lock = objc.IBOutlet()

    chat_local_endpoint = objc.IBOutlet()
    chat_remote_endpoint = objc.IBOutlet()
    chat_connection_mode = objc.IBOutlet()
    chat_tls_lock = objc.IBOutlet()

    def __new__(cls, *args, **kwargs):
        return cls.alloc().init()

    def __init__(self, sessionController):
        self.visible = False

        self.notification_center = NotificationCenter()
        self.sessionController = sessionController
        self.notification_center.add_observer(self, sender=self.sessionController)

        self.audio_stream = None
        self.chat_stream = None

        self.add_audio_stream()
        self.add_chat_stream()

        self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(1.0, self, "updateTimer:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSModalPanelRunLoopMode)
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSDefaultRunLoopMode)
        NSBundle.loadNibNamed_owner_("SessionInfoPanel", self)

        sessionBoxTitle = NSAttributedString.alloc().initWithString_attributes_("SIP Session", NSDictionary.dictionaryWithObject_forKey_(NSColor.orangeColor(), NSForegroundColorAttributeName))
        self.sessionBox.setTitle_(sessionBoxTitle)       

        audioBoxTitle = NSAttributedString.alloc().initWithString_attributes_("Audio RTP Stream", NSDictionary.dictionaryWithObject_forKey_(NSColor.orangeColor(), NSForegroundColorAttributeName))
        self.audioBox.setTitle_(audioBoxTitle)       

        chatBoxTitle = NSAttributedString.alloc().initWithString_attributes_("Chat MSRP Stream", NSDictionary.dictionaryWithObject_forKey_(NSColor.orangeColor(), NSForegroundColorAttributeName))
        self.chatBox.setTitle_(chatBoxTitle)       

        self.audio_packet_loss_graph.setDataQueue_([])
        self.audio_packet_loss_graph.setLineWidth_(1.0)
        self.audio_packet_loss_graph.setLineSpacing_(1.0)
        self.audio_packet_loss_graph.setAboveLimit_(4)

        self.audio_rtt_graph.setDataQueue_([])
        self.audio_rtt_graph.setLineWidth_(1.0)
        self.audio_rtt_graph.setLineSpacing_(1.0)
        self.audio_rtt_graph.setAboveLimit_(200)

        self.audio_jitter_graph.setDataQueue_([])
        self.audio_jitter_graph.setLineWidth_(1.0)
        self.audio_jitter_graph.setLineSpacing_(1.0)
        self.audio_jitter_graph.setAboveLimit_(100)

        self.resetSession()
        self.resetAudio()
        self.resetChat()
        self.updatePanelValues()

    def remove_session(self):
        if self.sessionController is not None:
            self.notification_center.remove_observer(self, sender=self.sessionController)
            self.sessionController = None
        
    def add_audio_stream(self):
        if self.sessionController.hasStreamOfType("audio") and self.audio_stream is None:
            self.audio_stream = self.sessionController.streamHandlerOfType("audio")
            self.notification_center.add_observer(self, sender=self.audio_stream)
            self.notification_center.add_observer(self, sender=self.audio_stream.stream)

    def add_chat_stream(self):
        if self.sessionController.hasStreamOfType("chat") and self.chat_stream is None:
            self.chat_stream = self.sessionController.streamHandlerOfType("chat")
            self.notification_center.add_observer(self, sender=self.chat_stream)
            self.notification_center.add_observer(self, sender=self.chat_stream.stream)

    def remove_audio_stream(self):
        if self.audio_stream is not None:
            self.notification_center.remove_observer(self, sender=self.audio_stream)
            self.notification_center.remove_observer(self, sender=self.audio_stream.stream)
            self.audio_stream = None
            self.updateAudioStatus()

    def remove_chat_stream(self):
        if self.chat_stream is not None:
            self.notification_center.remove_observer(self, sender=self.chat_stream)
            self.notification_center.remove_observer(self, sender=self.chat_stream.stream)
            self.chat_stream = None

    def _NH_BlinkDidRenegotiateStreams(self, notification):
        if notification.data.action == 'remove':
            for stream in notification.data.streams:
                if stream.type == 'audio':
                    self.remove_audio_stream()
                elif stream.type == 'chat':
                    self.remove_chat_stream()
        elif notification.data.action == 'add':
            for stream in notification.data.streams:
                if stream.type == 'audio':
                    self.add_audio_stream()
                elif stream.type == 'chat':
                    self.add_chat_stream()

        self.updatePanelValues()

    @allocate_autorelease_pool
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def resetSession(self): 
        self.local_endpoint.setStringValue_('')
        self.remote_endpoint.setStringValue_('')
        self.remote_ua.setStringValue_('')
        self.conference.setStringValue_('')
        self.status.setStringValue_('')
        self.duration.setStringValue_('')

    def resetAudio(self):
        self.audio_status.setStringValue_('')
        self.audio_codec.setStringValue_('')
        self.audio_sample_rate.setStringValue_('')
        self.audio_srtp_active.setStringValue_('')
        self.audio_local_endpoint.setStringValue_('')
        self.audio_remote_endpoint.setStringValue_('')
        self.audio_ice_negotiation.setStringValue_('')
        self.audio_ice_local_candidate.setStringValue_('')
        self.audio_ice_remote_candidate.setStringValue_('')
        self.audio_rtt.setStringValue_('')
        self.audio_packet_loss.setStringValue_('')
        self.audio_jitter.setStringValue_('')

    def resetChat(self):
        self.chat_local_endpoint.setStringValue_('')
        self.chat_remote_endpoint.setStringValue_('')
        self.chat_connection_mode.setStringValue_('')
    
    def updatePanelValues(self):
        self.updateSession()
        self.updateAudio()
        self.updateChat()

    def updateSession(self):
        if self.sessionController is not None:
            self.remote_party.setStringValue_(self.sessionController.getTitleFull())

            self.status.setStringValue_(self.sessionController.state.title())
            self.conference.setStringValue_('%d Participants' % len(self.sessionController.conference_info.users) if self.sessionController.conference_info is not None and self.sessionController.remote_focus else 'No')

            if hasattr(self.sessionController.session, 'remote_user_agent') and self.sessionController.session.remote_user_agent is not None:
                self.remote_ua.setStringValue_(self.sessionController.session.remote_user_agent)

            if self.sessionController.session is not None and self.sessionController.session.peer_address is not None and self.sessionController.session.transport is not None:
                transport = self.sessionController.session.transport
                self.remote_endpoint.setStringValue_('%s:%s' % (transport, str(self.sessionController.session.peer_address)))
                local_contact = self.sessionController.account.contact[transport]
                self.local_endpoint.setStringValue_('%s:%s:%d' % (transport, local_contact.host, local_contact.port))
                self.tls_lock.setHidden_(False if transport == 'tls' else True)

    def updateAudio(self):
        if self.audio_stream is None or self.audio_stream.stream is None:
            self.resetAudio()
        else:
            self.updateAudioStatus()
            self.audio_rtt.setStringValue_(self.audio_stream.last_latency if self.audio_stream.last_latency!= '0 ms' else '')
            self.audio_packet_loss.setStringValue_(self.audio_stream.last_packet_loss)

            if self.audio_stream.stream.sample_rate and self.audio_stream.stream.codec:
                self.audio_codec.setStringValue_(self.audio_stream.stream.codec)
                self.audio_sample_rate.setStringValue_("%0.fkHz" % (self.audio_stream.stream.sample_rate/1000))
                self.audio_srtp_active.setStringValue_('Enable' if self.audio_stream.stream.srtp_active else 'Disabled')
                self.audio_srtp_lock.setHidden_(False if self.audio_stream.stream.srtp_active else True)
            else:   
                self.audio_codec.setStringValue_('')
                self.audio_sample_rate.setStringValue_('')
                self.audio_srtp_active.setStringValue_('')
                self.audio_srtp_lock.setHidden_(True)
                              
            self.audio_local_endpoint.setStringValue_('%s:%s' % (self.audio_stream.stream.local_rtp_address, self.audio_stream.stream.local_rtp_port) if self.audio_stream.stream.local_rtp_address else '')
            self.audio_remote_endpoint.setStringValue_('%s:%s' % (self.audio_stream.stream.remote_rtp_address, self.audio_stream.stream.remote_rtp_port) if self.audio_stream.stream.remote_rtp_address else '')

            if self.audio_stream.stream.ice_active:
                if self.audio_stream.stream.local_rtp_candidate_type is not None:
                    try:
                        candidate = ice_candidates[self.audio_stream.stream.local_rtp_candidate_type]
                    except KeyError:
                        candidate = self.audio_stream.stream.local_rtp_candidate_type.capitalize()
                else:
                    candidate = ''

                self.audio_ice_local_candidate.setStringValue_(candidate)

                if self.audio_stream.stream.remote_rtp_candidate_type is not None:
                    try:
                        candidate = ice_candidates[self.audio_stream.stream.remote_rtp_candidate_type]
                    except KeyError:
                        candidate = self.audio_stream.stream.remote_rtp_candidate_type.capitalize()
                else:
                    candidate = ''

                self.audio_ice_remote_candidate.setStringValue_(candidate)

                ice_status = self.audio_stream.ice_negotiation_status if self.audio_stream.ice_negotiation_status is not None else ''
                if ice_status:
                    if self.audio_stream.stream.local_rtp_candidate_type != 'relay' and self.audio_stream.stream.remote_rtp_candidate_type != 'relay':
                        ice_status += ' (Peer to Peer)'
                    else:
                        ice_status += ' (Server Relayed)'
            else:
                self.audio_ice_local_candidate.setStringValue_('')
                self.audio_ice_remote_candidate.setStringValue_('')
                ice_status = ''

            self.audio_ice_negotiation.setStringValue_(ice_status)

    def updateChat(self):
        if self.chat_stream is None or self.chat_stream.stream is None or self.chat_stream.stream.msrp is None:
            self.resetChat()
        else:
            self.chat_local_endpoint.setStringValue_(str(self.chat_stream.stream.msrp.full_local_path[-1]))
            if len(self.chat_stream.stream.msrp.full_local_path) > 1:
                self.chat_remote_endpoint.setStringValue_(str(self.chat_stream.stream.msrp.full_local_path[0]))
            else:
                self.chat_remote_endpoint.setStringValue_(str(self.chat_stream.stream.msrp.full_remote_path[0]))

            self.chat_connection_mode.setStringValue_(self.chat_stream.stream.local_role.title())
    
    def updateTimer_(self, timer):
        self.updateDuration()

        if self.audio_stream:
            self.audio_rtt_graph.setDataQueue_(self.audio_stream.latency_history)
            self.audio_packet_loss_graph.setDataQueue_(self.audio_stream.packet_loss_history)
            self.audio_jitter_graph.setDataQueue_(self.audio_stream.jitter_history)

    def updateDuration(self):
        if self.sessionController is not None and self.sessionController.session is not None:
            if self.sessionController.session.end_time:
                now = self.sessionController.session.end_time
            else:
                now = datetime.datetime(*time.localtime()[:6])

            if self.sessionController.session.start_time and now >= self.sessionController.session.start_time:
                elapsed = now - self.sessionController.session.start_time
                h = elapsed.seconds / (60*60)
                m = (elapsed.seconds / 60) % 60
                s = elapsed.seconds % 60
                text = u"%02i:%02i:%02i"%(h,m,s)
                self.duration.setStringValue_(text)
            else:
                self.duration.setStringValue_('')

    def updateAudioStatus(self):
        if self.audio_stream is None:
            self.audio_status.setStringValue_("")
        else:
            if self.audio_stream.holdByLocal:
                self.audio_status.setStringValue_(u"On Hold")
            elif self.audio_stream.holdByRemote:
                self.audio_status.setStringValue_(u"Hold by Remote")
            elif self.audio_stream.status == STREAM_CONNECTED:
                self.audio_status.setStringValue_(u"Active")
            else:   
                self.audio_status.setStringValue_("")
            
    @run_in_gui_thread
    def _NH_AudioSessionInformationGotUpdated(self, notification):
        self.audio_rtt.setStringValue_(notification.data.latency if self.audio_stream.last_latency!= '0 ms' else '')
        self.audio_packet_loss.setStringValue_(notification.data.loss)
        self.audio_jitter.setStringValue_(notification.data.jitter)

    @run_in_gui_thread
    def _NH_BlinkSessionChangedState(self, notification):
        self.status.setStringValue_(self.sessionController.state.title())

    @run_in_gui_thread
    def _NH_BlinkSentAddProposal(self, notification):
        self.status.setStringValue_('Propose Add Stream')

    def _NH_BlinkSentRemoveProposal(self, notification):
        self.status.setStringValue_('Propose Remove Stream')

    @run_in_gui_thread
    def _NH_BlinkProposalGotRejected(self, notification):
        self.status.setStringValue_(self.sessionController.state.title())

    @run_in_gui_thread
    def _NH_BlinkStreamHandlersChanged(self, notification):
        self.status.setStringValue_(self.sessionController.state.title())

    @run_in_gui_thread
    def _NH_BlinkGotProposal(self, notification):
        self.status.setStringValue_('Receive Proposal')

    @run_in_gui_thread
    def _NH_AudioStreamICENegotiationDidFail(self, notification):
        if self.audio_stream is None:
            return
        self.audio_ice_negotiation.setStringValue_(self.audio_stream.ice_negotiation_status if self.audio_stream.ice_negotiation_status is not None else '')

    @run_in_gui_thread
    def _NH_AudioStreamICENegotiationDidSucceed(self, notification):
        if self.audio_stream is None:
            return
        self.audio_ice_negotiation.setStringValue_(self.audio_stream.ice_negotiation_status if self.audio_stream.ice_negotiation_status is not None else '')

    @run_in_gui_thread
    def _NH_BlinkSessionDidStart(self, notification):
        self.add_audio_stream()
        self.add_chat_stream()
        self.updatePanelValues()

    @run_in_gui_thread
    def _NH_AudioStreamDidChangeHoldState(self, notification):
        self.updateAudioStatus()

    @run_in_gui_thread
    def _NH_BlinkConferenceGotUpdate(self, notification):
        if self.sessionController.session is not None:
            self.conference.setStringValue_('%d Participants' % len(notification.data.conference_info.users))

    @run_in_gui_thread
    def _NH_BlinkStreamHandlerChangedState(self, notification):
        self.updatePanelValues()

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        self.notification_center.post_notification("SessionInfoPanelIsVisible", sender=self.sessionController)

    def hide(self):
        self.window.orderOut_(None)
        self.notification_center.post_notification("SessionInfoPanelIsHidden", sender=self.sessionController)

    def toggle(self):
        if self.window.isVisible():
            self.hide()
        else:
            self.show()

    def windowShouldClose_(self, sender):
        self.window.orderOut_(None)
        self.notification_center.post_notification("SessionInfoPanelIsHidden", sender=self.sessionController)

    def close(self):
        self.timer.invalidate()
        self.timer = None

        self.remove_session()
        self.remove_audio_stream()
        self.remove_chat_stream()

        self.audio_packet_loss_buffer = None
        self.audio_rtt_buffer = None
        self.window.orderOut_(None)
        self.notification_center.post_notification("SessionInfoPanelIsHidden", sender=self.sessionController)
        self.visible = False


class CBGraphView(NSView):
    #
    #  CBGraphView.py
    #  CBGraphView
    #
    #  Created by boB Rudis on 1/6/09.
    #  Copyright (c) 2009 RUDIS DOT NET. All rights reserved.
    #

    dataQueue = None     # holds the data we'll be graphing
    gradientGray = None  # the gray color of the black->gray gradient we are using
    lineColor = None     # the color to make the bars
    grad = None          # the gradient object
    lineWidth = 1.0      # default bar width (1 "pixel")
    lineSpacing = 0.0    # default spacing between bars to no space
    limit = 1000
    
    def initWithFrame_(self, frame):
        """ basic constructor for views. here we init colors and gradients """

        self = super(CBGraphView, self).initWithFrame_(frame)

        if self:
            self.gradientGray = NSColor.colorWithCalibratedRed_green_blue_alpha_(50/255.0, 50/255.0, 50/255.0, 1.0)
            self.lineColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(33/255.0, 104/255.0, 198/255.0, 1.0)
            self.lineColorAboveLimit = NSColor.orangeColor()
            self.borderColor = NSColor.whiteColor()

            self.grad = NSGradient.alloc().initWithStartingColor_endingColor_(NSColor.blackColor(), self.gradientGray)
            self.grad.retain()

        return self
        
    def setDataQueue_(self, dq):
        """ set the data object we are graphig """
        self.dataQueue = dq
        self.setNeedsDisplay_(YES)
        
    def setLineWidth_(self, width):
        """ let user change line (bar) width """
        self.lineWidth = width

    def setAboveLimit_(self, limit):
        """ show red color above limit """
        self.limit = limit
        
    def setLineSpacing_(self, spacing):
        """ let user change spacing bewteen bars (lines) """
        self.lineSpacing = spacing
     
    def setLineColor_(self, color):
        """ let user change line (bar) color """
        self.lineColor = color

    def setBorderColor_(self, color):
        """ let user change border color """
        self.borderColor = color
        
    def setBackgroundGradientStart_andEnd_(self, startColor, endColor):
        """ let user change the gradient colors """
        self.grad.release()
        self.grad = NSGradient.alloc().initWithStartingColor_endingColor_(startColor, endColor)
        self.grad.retain()
        
    def isOpaque(self):
        """ are we opaque? why, of course we are! """
        return YES
        
    def dealloc(self):
        """ default destructor """
        self.grad.release()
        super(CBGraphView, self).dealloc()

    def drawRect_(self, rect):
        """ we raw the background gradient and graph outline then clip the inner rect
            and draw the bars """

        bounds = self.bounds() # get our view bounds
        insetBounds = NSInsetRect(bounds, 2, 2) # set the inside ortion
        
        r = NSBezierPath.bezierPathWithRect_(bounds) # creatre a new bezier rect
        self.grad.drawInBezierPath_angle_(r, 90.0) # and draw gradient in it
        
        self.borderColor.set() # set border to white
        NSBezierPath.setDefaultLineWidth_(1.0) # set line width for outline
        NSBezierPath.strokeRect_(bounds) # draw outline

        NSBezierPath.clipRect_(insetBounds) # set the clipping path
        insetBounds.size.height -= 2 # leave room at the top (purely my personal asthetic

        buf = None  # init the list structure we will be using
        
        if self.dataQueue:
            buf = self.dataQueue.get()  # get the list
        
        if buf:
            rbuf = [ q for q in buf if q ] # filter "None" from the list
            rbuf.reverse() # reverse the list
            
            barRect = NSRect() # init the rect
                
            try:      
                maxB = max(rbuf) # find out the max value so we can scale the graph
            except ValueError:
                maxB = 0

            # disable anti-aliasing since it looks bad
            shouldAA = NSGraphicsContext.currentContext().shouldAntialias()
            NSGraphicsContext.currentContext().setShouldAntialias_(NO)

            # draw each bar

            barRect.origin.x = insetBounds.size.width - self.lineWidth + 2
            for b in rbuf:
                if b:
                    if b >= self.limit:
                        self.lineColorAboveLimit.set() # set drawing color
                    else:
                        self.lineColor.set() # set drawing color

                    barRect.origin.y = insetBounds.origin.y
                    barRect.size.width = self.lineWidth
                    barRect.size.height = ((int(b) * insetBounds.size.height) / maxB)
                    
                    NSBezierPath.fillRect_(barRect)
                    
                    barRect.origin.x = barRect.origin.x - self.lineWidth - self.lineSpacing
                    
            NSGraphicsContext.currentContext().setShouldAntialias_(shouldAA)


class RingBuffer:
    def __init__(self, size):
        """ init with # of elements in the queue """
        self.data = [ None for i in xrange(size)  ]

    def append(self, x):
        """ take away one and put one in """
        self.data.pop(0)
        self.data.append(x)

    def get(self):
        """ return the list so we can manipulate it """
        return self.data
