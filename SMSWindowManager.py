# Copyright (C) 2009-2011 AG Projects. See LICENSE for details.
#

from Foundation import *
from AppKit import *

import datetime
import re

from application.notification import IObserver, NotificationCenter
from application.python.util import Null
from zope.interface import implements

from sipsimple.core import SIPURI
from sipsimple.util import TimestampedNotificationData
from sipsimple.payloads.iscomposing import IsComposingMessage
from sipsimple.streams.applications.chat import CPIMMessage, CPIMParserError

import SIPManager

from BlinkLogger import BlinkLogger
from SMSViewController import SMSViewController
from util import *

class SMSWindowController(NSWindowController):
    implements(IObserver)

    tabView = objc.IBOutlet()
    tabSwitcher = objc.IBOutlet()

    def initWithOwner_(self, owner):
        self= super(SMSWindowController, self).init()
        if self:
            self._owner = owner
            NSBundle.loadNibNamed_owner_("SMSSession", self)
            self.unreadMessageCounts = {}
        return self

    def selectedSession(self):
        activeTab = self.tabView.selectedTabViewItem()
        if activeTab:
            return activeTab.identifier()
        return None
    
    def updateTitle(self, display_name = None):
        session = self.selectedSession()
        if session:
            sip_address = '%s@%s' % (session.target_uri.user, session.target_uri.host)
            if display_name and display_name != sip_address:
                title = u"SMS to %s <%s>" % (display_name, format_identity(session.target_uri))
            else:
                title = u"SMS to %s" %  format_identity(session.target_uri)
        else:
            title = u"SMS"
        self.window().setTitle_(title)

    def noteNewMessageForSession_(self, session):
        index = self.tabView.indexOfTabViewItemWithIdentifier_(session)
        if index == NSNotFound:
            return
        tabItem = self.tabView.tabViewItemAtIndex_(index)            
        item = self.tabSwitcher.itemForTabViewItem_(tabItem)
        if item:
            if self.tabView.selectedTabViewItem() == tabItem:
                item.setBadgeLabel_("")
            else:
                count = self.unreadMessageCounts[session] = self.unreadMessageCounts.get(session, 0) + 1
                item.setBadgeLabel_(str(count))

    def noteView_isComposing_(self, smsview, flag):
        index = self.tabView.indexOfTabViewItemWithIdentifier_(smsview)
        if index == NSNotFound:
            return
        tabItem = self.tabView.tabViewItemAtIndex_(index)
        item = self.tabSwitcher.itemForTabViewItem_(tabItem)
        if item:
            item.setComposing_(flag)

    def addViewer_(self, viewer):
        tabItem = NSTabViewItem.alloc().initWithIdentifier_(viewer)
        tabItem.setView_(viewer.getContentView())
        sip_address = '%s@%s' % (viewer.target_uri.user, viewer.target_uri.host)
        if viewer.display_name and viewer.display_name != sip_address:
            tabItem.setLabel_("%s" % viewer.display_name)
        else:
            tabItem.setLabel_(format_identity(viewer.target_uri))
        self.tabSwitcher.addTabViewItem_(tabItem)
        self.tabSwitcher.selectLastTabViewItem_(None)
        self.updateTitle(viewer.display_name)
        self.window().makeFirstResponder_(viewer.chatViewController.inputText)

    def removeViewer_(self, viewer):
        i = self.tabView.indexOfTabViewItemWithIdentifier_(viewer)
        if i != NSNotFound:
            item = self.tabView.tabViewItemAtIndex_(i)
            self.tabSwitcher.removeTabViewItem_(item)
    
    @property
    def viewers(self):
        return (item.identifier() for item in self.tabView.tabViewItems())
    
    def close_(self, sender):
        selected = self.selectedSession()
        if self.unreadMessageCounts.has_key(selected):
            del self.unreadMessageCounts[selected]
        self.tabSwitcher.removeTabViewItem_(self.tabView.selectedTabViewItem())
        if self.tabView.numberOfTabViewItems() == 0:
            self.window().performClose_(None)

    def tabView_shouldCloseTabViewItem_(self, sender, item):
        if self.unreadMessageCounts.has_key(item.identifier()):
            del self.unreadMessageCounts[item.identifier()]
        return True

    def tabView_didSelectTabViewItem_(self, sender, item):
        self.updateTitle()
        if self.unreadMessageCounts.has_key(item.identifier()):
            del self.unreadMessageCounts[item.identifier()]
            self.noteNewMessageForSession_(item.identifier())

    def tabViewDidChangeNumberOfTabViewItems_(self, tabView):
        if tabView.numberOfTabViewItems() == 0:
            self.window().performClose_(None)

    def tabView_didDettachTabViewItem_atPosition_(self, tabView, item, pos):
        if tabView.numberOfTabViewItems() > 1:
            session = item.identifier()
            window = SMSWindowManager().dettachSMSViewer(session)
            if window:
                window.window().setFrameOrigin_(pos)

    def windowShouldClose_(self, sender):
        for item in self.tabView.tabViewItems().copy():
            self.tabSwitcher.removeTabViewItem_(item)
        if self in SMSWindowManager().windows:
            SMSWindowManager().windows.remove(self)
        return True

    @objc.IBAction
    def toolbarButtonClicked_(self, sender):
        if sender.tag() == 100: # smileys
            chatViewController = self.selectedSession().chatViewController
            chatViewController.expandSmileys = not chatViewController.expandSmileys
            if chatViewController.expandSmileys:
                sender.setImage_(NSImage.imageNamed_("smiley_on"))
            else:
                sender.setImage_(NSImage.imageNamed_("smiley_off"))
        elif sender.tag() == 101: # history
            contactWindow = self._owner._owner
            contactWindow.showChatTranscripts_(None)
            session = self.selectedSession()
            contactWindow.transcriptViewer.filterByContactAccount(format_identity(session.target_uri), session.account)


SMSWindowManagerInstance = None

def SMSWindowManager():
    global SMSWindowManagerInstance
    if SMSWindowManagerInstance is None:
        SMSWindowManagerInstance = SMSWindowManagerClass.alloc().init()
    return SMSWindowManagerInstance


class SMSWindowManagerClass(NSObject):
    implements(IObserver)

    #__metaclass__ = Singleton

    windows = []

    def init(self):
        self = super(SMSWindowManagerClass, self).init()
        if self:
            self.notification_center = NotificationCenter()
            self.notification_center.add_observer(self, name="SIPEngineGotMessage")
        return self
    
    def setOwner_(self, owner):
        self._owner = owner

    def openMessageWindow(self, target, target_name, account, create_if_needed=True, note_new_message=True):
        for window in self.windows:
            for viewer in window.viewers:
                if viewer.matchesTargetAccount(target, account):
                    break
            else:
                continue
            break
        else:
            window, viewer = None, None

        if not viewer and create_if_needed:
            viewer = SMSViewController.alloc().initWithAccount_target_name_(account, target, target_name)
            if not self.windows:
                window = SMSWindowController.alloc().initWithOwner_(self)
                self.windows.append(window)
            else:
                window = self.windows[0]
            window.addViewer_(viewer)
        elif viewer:
            window = self.windowForViewer(viewer)

        if window:
            if note_new_message:
                window.window().makeKeyAndOrderFront_(None)
                NSApp.delegate().noteNewMessage(window)

        return viewer

    def dettachSMSViewer(self, viewer):
        oldWindow = self.windowForViewer(viewer)
        oldWindow.removeViewer_(viewer)
        window = SMSWindowController.alloc().initWithOwner_(self)
        self.windows.append(window)    
        window.addViewer_(viewer)
        window.window().makeKeyAndOrderFront_(None)
        return window

    def windowForViewer(self, viewer):
        for window in self.windows:
            if viewer in window.viewers:
                return window
        else:
            return None

    @allocate_autorelease_pool
    @run_in_gui_thread
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification.sender, notification.data)

    def _NH_SIPEngineGotMessage(self, sender, data):
        account = SIPManager.SIPManager().account_for_contact(data.request_uri)
        if not account:
            BlinkLogger().log_warning("Could not find recipient account for message to %s, using default" % data.request_uri)
            account = SIPManager.SIPManager().get_default_account()

        is_cpim = False
        cpim_message = None
        replication_message = False

        if data.content_type == 'message/cpim':
            try:
                cpim_message = CPIMMessage.parse(data.body)
            except CPIMParserError:
                BlinkLogger().log_warning("SMS from %s has invalid CPIM content" % format_identity(data.from_header))
                return
            else:
                is_cpim = True
                body = cpim_message.body
                content_type = cpim_message.content_type
                sender_identity = cpim_message.sender or data.from_header
                if cpim_message.sender and data.from_header.uri == data.to_header.uri and data.from_header.uri == cpim_message.sender.uri:
                    replication_message = True
                    window_tab_identity = cpim_message.recipients[0] if cpim_message.recipients else data.to_header
                else:
                    window_tab_identity = data.from_header
        else:
            body = data.body.decode('utf-8')
            content_type = data.content_type
            sender_identity = data.from_header
            window_tab_identity = sender_identity

        is_html = content_type == 'text/html'

        if content_type in ('text/plain', 'text/html'):
            BlinkLogger().log_info("Got SMS from %s" % format_identity(sender_identity))
        elif content_type == 'application/im-iscomposing+xml':
            # body must not be utf-8 decoded
            body = cpim_message.body if is_cpim else data.body
            msg = IsComposingMessage.parse(body)
            state = msg.state.value
            refresh = msg.refresh.value if msg.refresh is not None else None
            content_type = msg.contenttype.value if msg.contenttype is not None else None
            last_active = msg.last_active.value if msg.last_active is not None else None

            viewer = self.openMessageWindow(SIPURI.new(window_tab_identity.uri), window_tab_identity.display_name, account, create_if_needed=False, note_new_message=False)
            if viewer:
                viewer.gotIsComposing(self.windowForViewer(viewer), state, refresh, last_active)
            return
        else:
            BlinkLogger().log_warning("SMS from %s has unknown content-type %s" % (format_identity(data.from_header), data.content_type))
            return

        # display the message
        note_new_message = False if replication_message else True
        viewer = self.openMessageWindow(SIPURI.new(window_tab_identity.uri), window_tab_identity.display_name, account, note_new_message=note_new_message)
        self.windowForViewer(viewer).noteNewMessageForSession_(viewer)
        replication_state = None
        replication_timestamp = None

        if replication_message:
            replicated_response_code = data.headers.get('X-Replication-Code', Null).body
            if replicated_response_code == '202':
                replication_state = 'deferred'
            elif replicated_response_code == '200':
                replication_state = 'delivered'
            else:
                replication_state = 'failed'
            replicated_timestamp = data.headers.get('X-Replication-Timestamp', Null).body
            try:
                replication_timestamp = datetime.datetime.strptime(replicated_timestamp, '%Y-%m-%d %H:%M:%S')
            except (TypeError, ValueError):
                replication_timestamp = datetime.datetime.utcnow()

        viewer.gotMessage(sender_identity, body, is_html, replication_state, replication_timestamp)
        self.windowForViewer(viewer).noteView_isComposing_(viewer, False)

        if replication_message:
            return

        if not self.windowForViewer(viewer).window().isKeyWindow():
            # notify growl
            growl_data = TimestampedNotificationData()
            if is_html:
                growl_data.content = html2txt(body)
            else:
                growl_data.content = body
            growl_data.sender = format_identity_simple(sender_identity)
            self.notification_center.post_notification("GrowlGotSMS", sender=self, data=growl_data)

