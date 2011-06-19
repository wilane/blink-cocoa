# Copyright (C) 2009-2011 AG Projects. See LICENSE for details.
#

from Foundation import *
from AppKit import *
import objc

import datetime
import os
import re
import string

from application.notification import NotificationCenter, IObserver
from application.python import Null
from sipsimple.account import AccountManager, Account, BonjourAccount
from sipsimple.application import SIPApplication
from sipsimple.audio import WavePlayer
from sipsimple.conference import AudioConference
from sipsimple.configuration.settings import SIPSimpleSettings
from sipsimple.session import IllegalStateError
from sipsimple.session import SessionManager
from sipsimple.threading.green import run_in_green_thread
from operator import attrgetter
from zope.interface import implements

import ContactOutlineView
import ListView
import SMSWindowManager

import PresencePolicy
from PresencePolicy import fillPresenceMenu
from AccountSettings import AccountSettings
from AlertPanel import AlertPanel
from AudioSession import AudioSession
from BlinkLogger import BlinkLogger
from HistoryManager import SessionHistory
from HistoryViewer import HistoryViewer
from ContactCell import ContactCell
from ContactListModel import BlinkContact, BlinkContactGroup, contactIconPathForURI, saveContactIcon
from DebugWindow import DebugWindow
from EnrollmentController import EnrollmentController
from FileTransferWindowController import FileTransferWindowController, openFileTransferSelectionDialog
from ConferenceController import JoinConferenceWindowController, AddParticipantsWindowController
from SessionController import SessionController
from SIPManager import MWIData
from VideoMirrorWindowController import VideoMirrorWindowController
from resources import Resources
from util import *

SearchContactToolbarIdentifier= u"SearchContact"

PARTICIPANTS_MENU_ADD_CONFERENCE_CONTACT = 314
PARTICIPANTS_MENU_ADD_CONTACT = 301
PARTICIPANTS_MENU_REMOVE_FROM_CONFERENCE = 310
PARTICIPANTS_MENU_MUTE = 315
PARTICIPANTS_MENU_INVITE_TO_CONFERENCE = 312
PARTICIPANTS_MENU_GOTO_CONFERENCE_WEBSITE = 313
PARTICIPANTS_MENU_START_AUDIO_SESSION = 320
PARTICIPANTS_MENU_START_CHAT_SESSION = 321
PARTICIPANTS_MENU_START_VIDEO_SESSION = 322
PARTICIPANTS_MENU_SEND_FILES = 323


class PhotoView(NSImageView):
    entered = False
    callback = None

    def mouseDown_(self, event):
        self.callback(self)

    def mouseEntered_(self, event):
        self.entered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.entered = False
        self.setNeedsDisplay_(True)

    def updateTrackingAreas(self):
        rect = NSZeroRect
        rect.size = self.frame().size
        self.addTrackingRect_owner_userData_assumeInside_(rect, self, None, False)

    def drawRect_(self, rect):
        NSColor.whiteColor().set()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 5.0, 5.0)
        path.fill()

        frect = NSZeroRect
        if self.image():
            frect.size = self.image().size()
            self.image().drawInRect_fromRect_operation_fraction_(NSInsetRect(rect, 3, 3), frect, NSCompositeSourceOver, 1.0)
        NSColor.blackColor().colorWithAlphaComponent_(0.5).set()
        if self.entered:
            path.fill()


class ContactWindowController(NSWindowController):
    implements(IObserver)

    accounts = []
    chatWindows = []
    model = objc.IBOutlet()
    backend = None
    loggerModel = None
    sessionControllers = []
    participants = []

    searchResultsModel = objc.IBOutlet()
    fileTranfersWindow = objc.IBOutlet()

    debugWindow = None
    mirrorWindow = None

    loaded = False
    collapsedState = False
    originalSize = None
    originalWindowPosition = None
    alertPanel = None
    accountSettingsPanels = {}

    authFailPopupShown = False

    originalPresenceStatus = None
    disbandingConference = False

    drawer = objc.IBOutlet()
    mainTabView = objc.IBOutlet()
    drawerSplitView = objc.IBOutlet()
    participantsView = objc.IBOutlet()
    participantsTableView = objc.IBOutlet()
    participantMenu = objc.IBOutlet()
    sessionsView = objc.IBOutlet()
    sessionListView = objc.IBOutlet()
    drawerSplitterPosition = None

    searchBox = objc.IBOutlet()
    accountPopUp = objc.IBOutlet()
    contactOutline = objc.IBOutlet()
    actionButtons = objc.IBOutlet()
    addContactButton = objc.IBOutlet()
    addContactButtonSearch = objc.IBOutlet()
    addContactButtonDialPad = objc.IBOutlet()
    conferenceButton = objc.IBOutlet()

    contactContextMenu = objc.IBOutlet()

    photoImage = objc.IBOutlet()
    statusPopUp = objc.IBOutlet()
    nameText = objc.IBOutlet()
    statusText = objc.IBOutlet()

    muteButton = objc.IBOutlet()
    silentButton = objc.IBOutlet()

    searchOutline = objc.IBOutlet()
    notFoundText = objc.IBOutlet()
    notFoundTextOffset = None
    searchOutlineTopOffset = None

    addContactToConferenceDialPad = objc.IBOutlet()

    blinkMenu = objc.IBOutlet()
    historyMenu = objc.IBOutlet()
    recordingsMenu = objc.IBOutlet()
    contactsMenu = objc.IBOutlet()
    devicesMenu = objc.IBOutlet()
    statusMenu = objc.IBOutlet()
    toolsMenu = objc.IBOutlet()
    callMenu = objc.IBOutlet()
    presenceMenu = objc.IBOutlet()

    chatMenu = objc.IBOutlet()
    desktopShareMenu = objc.IBOutlet()

    historyViewer = None

    picker = None

    searchInfoAttrs = NSDictionary.dictionaryWithObjectsAndKeys_(
                    NSFont.systemFontOfSize_(NSFont.labelFontSize()), NSFontAttributeName,
                    NSColor.grayColor(), NSForegroundColorAttributeName)

    conference = None
    joinConferenceWindow = None
    addParticipantsWindow = None

    silence_player = None
    dialPadView = objc.IBOutlet()


    def awakeFromNib(self):
        # check how much space there is left for the search Outline, so we can restore it after
        # minimizing
        self.searchOutlineTopOffset = NSHeight(self.searchOutline.enclosingScrollView().superview().frame()) - NSHeight(self.searchOutline.enclosingScrollView().frame())

        # save the NSUser icon to disk so that it can be used from html
        icon = NSImage.imageNamed_("NSUser")
        icon.setSize_(NSMakeSize(32, 32))
        saveContactIcon(icon, "default_user_icon")

        self.contactOutline.setRowHeight_(40)
        self.contactOutline.setTarget_(self)
        self.contactOutline.setDoubleAction_("actionButtonClicked:")
        self.contactOutline.setDraggingSourceOperationMask_forLocal_(NSDragOperationMove, True)
        self.contactOutline.registerForDraggedTypes_(NSArray.arrayWithObjects_("dragged-contact", NSFilenamesPboardType))

        self.searchOutline.setTarget_(self)
        self.searchOutline.setDoubleAction_("actionButtonClicked:")
        self.contactOutline.setDraggingSourceOperationMask_forLocal_(NSDragOperationCopy, True)
        self.searchOutline.registerForDraggedTypes_(NSArray.arrayWithObjects_("dragged-contact", NSFilenamesPboardType))

        self.chatMenu.setAutoenablesItems_(False)

        # save the position of this view, because when the window is collapsed
        # the position gets messed
        f = self.notFoundText.frame()
        self.notFoundTextOffset = NSHeight(self.notFoundText.superview().frame()) - NSMinY(f)

        self.mainTabView.selectTabViewItemWithIdentifier_("contacts")

        self.sessionListView.setSpacing_(0)

        self.participantsTableView.registerForDraggedTypes_(NSArray.arrayWithObject_("x-blink-sip-uri"))
        self.participantsTableView.setTarget_(self)
        self.participantsTableView.setDoubleAction_("doubleClickReceived:")

        nc = NotificationCenter()
        nc.add_observer(self, name="AudioDevicesDidChange")
        nc.add_observer(self, name="ActiveAudioSessionChanged")
        nc.add_observer(self, name="BlinkChatWindowClosed")
        nc.add_observer(self, name="BlinkConferenceGotUpdate")
        nc.add_observer(self, name="BlinkSessionChangedState")
        nc.add_observer(self, name="BlinkStreamHandlersChanged")
        nc.add_observer(self, name="BlinkMuteChangedState")
        nc.add_observer(self, name="BonjourAccountDidAddNeighbour")
        nc.add_observer(self, name="BonjourAccountDidUpdateNeighbour")
        nc.add_observer(self, name="BonjourAccountDidRemoveNeighbour")
        nc.add_observer(self, name="CFGSettingsObjectDidChange")
        nc.add_observer(self, name="DefaultAudioDeviceDidChange")
        nc.add_observer(self, name="MediaStreamDidInitialize")
        nc.add_observer(self, name="SIPApplicationDidStart")
        nc.add_observer(self, name="SIPAccountDidActivate")
        nc.add_observer(self, name="SIPAccountDidDeactivate")
        nc.add_observer(self, name="SIPAccountWillRegister")
        nc.add_observer(self, name="SIPAccountRegistrationDidSucceed")
        nc.add_observer(self, name="SIPAccountRegistrationDidFail")
        nc.add_observer(self, name="SIPAccountRegistrationDidEnd")
        nc.add_observer(self, name="BonjourAccountWillRegister")
        nc.add_observer(self, name="BonjourAccountRegistrationDidSucceed")
        nc.add_observer(self, name="BonjourAccountRegistrationDidFail")
        nc.add_observer(self, name="BonjourAccountRegistrationDidEnd")
        nc.add_observer(self, name="BlinkContactsHaveChanged")
        nc.add_observer(self, sender=AccountManager())

        ns_nc = NSNotificationCenter.defaultCenter()
        ns_nc.addObserver_selector_name_object_(self, "contactSelectionChanged:", NSOutlineViewSelectionDidChangeNotification, self.contactOutline)
        ns_nc.addObserver_selector_name_object_(self, "contactGroupExpanded:", NSOutlineViewItemDidExpandNotification, self.contactOutline)
        ns_nc.addObserver_selector_name_object_(self, "contactGroupCollapsed:", NSOutlineViewItemDidCollapseNotification, self.contactOutline)
        ns_nc.addObserver_selector_name_object_(self, "participantSelectionChanged:", NSTableViewSelectionDidChangeNotification, self.participantsTableView)
        ns_nc.addObserver_selector_name_object_(self, "drawerSplitViewDidResize:", NSSplitViewDidResizeSubviewsNotification, self.drawerSplitView)

        self.model.loadContacts()
        self.refreshContactsList()
        self.updateActionButtons()

        # never show debug window when application launches
        NSUserDefaults.standardUserDefaults().setInteger_forKey_(0, "ShowDebugWindow")

        self.window().setTitle_(NSApp.delegate().applicationName)

        white = NSDictionary.dictionaryWithObjectsAndKeys_(self.nameText.font(), NSFontAttributeName)
        self.statusPopUp.removeAllItems()

        while self.presenceMenu.numberOfItems() > 0:
            self.presenceMenu.removeItemAtIndex_(0)
        fillPresenceMenu(self.presenceMenu, self, "presentStatusChanged:")
        fillPresenceMenu(self.statusPopUp.menu(), self, "presentStatusChanged:", white)

        note = NSUserDefaults.standardUserDefaults().stringForKey_("PresenceNote")
        if note:
            self.statusText.setStringValue_(note)

        status = NSUserDefaults.standardUserDefaults().stringForKey_("PresenceStatus")
        if status:
            self.statusPopUp.selectItemWithTitle_(status)

        path = NSUserDefaults.standardUserDefaults().stringForKey_("PhotoPath")
        if path:
            self.photoImage.setImage_(NSImage.alloc().initWithContentsOfFile_(path))
        self.photoImage.callback = self.photoClicked

        self.window().makeFirstResponder_(self.contactOutline)

        # dialpad
        self.contactsMenu.itemWithTag_(42).setEnabled_(True if NSApp.delegate().applicationName == 'Blink Pro' else False)

        self.loaded = True


    def setup(self, sipManager):
        self.backend = sipManager
        self.backend.set_delegate(self)

    def setupFinished(self):
        if self.backend.is_muted():
            self.muteButton.setImage_(NSImage.imageNamed_("muted"))
            self.muteButton.setState_(NSOnState)
        else:
            self.muteButton.setImage_(NSImage.imageNamed_("mute"))
            self.muteButton.setState_(NSOffState)

        if self.backend.is_silent():
            self.silentButton.setImage_(NSImage.imageNamed_("belloff"))
            self.silentButton.setState_(NSOnState)
        else:
            self.silentButton.setImage_(NSImage.imageNamed_("bellon"))
            self.silentButton.setState_(NSOffState)
        active = self.activeAccount()
        if active and active.display_name != self.nameText.stringValue():
            self.nameText.setStringValue_(active.display_name or u"")

        # initialize debug window
        self.debugWindow = DebugWindow.alloc().init()

        # video mirror window
        self.mirrorWindow = VideoMirrorWindowController.alloc().init()

        # instantiate the SMS handler
        SMSWindowManager.SMSWindowManager().setOwner_(self)

        self.contactOutline.reloadData()

        self.accountSelectionChanged_(self.accountPopUp)

    def __del__(self):
        NSNotificationCenter.defaultCenter().removeObserver_(self)

    def showWindow_(self, sender):
        super(ContactWindowController, self).showWindow_(sender)

    def refreshAccountList(self):
        grayAttrs = NSDictionary.dictionaryWithObject_forKey_(NSColor.disabledControlTextColor(), NSForegroundColorAttributeName)
        self.accountPopUp.removeAllItems()
        self.accounts.sort(key=attrgetter('order'))

        account_manager = AccountManager()

        for account_info in (account_info for account_info in self.accounts if account_info.account.enabled):
            self.accountPopUp.addItemWithTitle_(account_info.name)
            item = self.accountPopUp.lastItem()
            item.setRepresentedObject_(account_info.account)
            if isinstance(account_info.account, BonjourAccount):
                image = NSImage.imageNamed_("NSBonjour")
                image.setScalesWhenResized_(True)
                image.setSize_(NSMakeSize(12,12))
                item.setImage_(image)
            else:
                if not account_info.registration_state == 'succeeded':
                    title = NSAttributedString.alloc().initWithString_attributes_(account_info.name, grayAttrs)
                    item.setAttributedTitle_(title)

            if account_info.account is account_manager.default_account:
                self.accountPopUp.selectItem_(item)

        if self.accountPopUp.numberOfItems() == 0:
            self.accountPopUp.addItemWithTitle_(u"No Accounts")
            self.accountPopUp.lastItem().setEnabled_(False)

        self.accountPopUp.menu().addItem_(NSMenuItem.separatorItem())
        self.accountPopUp.addItemWithTitle_(u"Add Account...")

        if account_manager.default_account:
            self.nameText.setStringValue_(account_manager.default_account.display_name or account_manager.default_account.id)
        else:
            self.nameText.setStringValue_(u'')

    def activeAccount(self):
        return self.accountPopUp.selectedItem().representedObject()

    def refreshContactsList(self):
        self.contactOutline.reloadData()
        for group in self.model.contactGroupsList:
            if group.expanded:
                self.contactOutline.expandItem_expandChildren_(group, False)

    def getSelectedContacts(self, includeGroups=False):
        contacts = []
        if self.mainTabView.selectedTabViewItem().identifier() == "contacts":
            outline = self.contactOutline
        elif self.mainTabView.selectedTabViewItem().identifier() == "search":
            outline = self.searchOutline

            if outline.selectedRowIndexes().count() == 0:
                try:
                    text = str(self.searchBox.stringValue())
                except:
                    self.sip_error("SIP address must not contain unicode characters (%s)" % unicode(self.searchBox.stringValue()))
                    return []

                if not text:
                    return []
                contact = BlinkContact(text, name=text)
                return [contact]
        else:
           return []

        selection= outline.selectedRowIndexes()
        item= selection.firstIndex()
        while item != NSNotFound:
            object= outline.itemAtRow_(item)
            if isinstance(object, BlinkContact):
                contacts.append(object)
            elif includeGroups and isinstance(object, BlinkContactGroup):
                contacts.append(object)
            item = selection.indexGreaterThanIndex_(item)

        return contacts

    def startIncomingSession(self, session, streams, answeringMachine=False):
        try:
            session_controller = (controller for controller in self.sessionControllers if controller.session == session).next()
        except StopIteration:
            session_controller = SessionController.alloc().initWithSession_(session)
            session_controller.setOwner_(self)
            self.sessionControllers.append(session_controller)
        session_controller.setAnsweringMachineMode_(answeringMachine)
        session_controller.handleIncomingStreams(streams, False)

    def acceptIncomingProposal(self, session, streams):
        try:
            session_controller = (controller for controller in self.sessionControllers if controller.session == session).next()
        except StopIteration:
            session.reject_proposal()
            session.log_info("Cannot find session controller for session: %s" % session)
        else:
            session_controller.handleIncomingStreams(streams, True)
            session.accept_proposal(streams)

    def windowShouldClose_(self, sender):
        ev = NSApp.currentEvent()
        if ev.type() == NSKeyDown:
            if ev.keyCode() == 53: # don't close on Escape key
                return False
        return True


    @allocate_autorelease_pool
    @run_in_gui_thread
    def handle_notification(self, notification):
        handler = getattr(self, '_NH_%s' % notification.name, Null)
        handler(notification)

    def _NH_SIPAccountManagerDidAddAccount(self, notification):
        account = notification.data.account
        self.accounts.insert(account.order, AccountInfo(account))
        self.refreshAccountList()

    def _NH_SIPAccountManagerDidRemoveAccount(self, notification):
        position = self.accounts.index(notification.data.account)
        del self.accounts[position]
        self.refreshAccountList()

    def _NH_SIPAccountDidActivate(self, notification):
        self.refreshAccountList()
        if notification.sender is BonjourAccount():
            self.model.setShowBonjourGroup(True)
            self.contactOutline.reloadData()

    def _NH_SIPAccountDidDeactivate(self, notification):
        self.refreshAccountList()
        if notification.sender is BonjourAccount():
            self.model.setShowBonjourGroup(False)
            self.contactOutline.reloadData()

    def _NH_SIPAccountWillRegister(self, notification):
        try:
            position = self.accounts.index(notification.sender)
        except ValueError:
            return
        self.accounts[position].registration_state = 'started'
        self.refreshAccountList()

    def _NH_SIPAccountRegistrationDidSucceed(self, notification):
        try:
            position = self.accounts.index(notification.sender)
        except ValueError:
            return
        self.accounts[position].registration_state = 'succeeded'
        self.refreshAccountList()

    def _NH_SIPAccountRegistrationDidFail(self, notification):
        try:
            position = self.accounts.index(notification.sender)
        except ValueError:
            return
        self.accounts[position].registration_state = 'failed'
        self.refreshAccountList()
        if isinstance(notification.sender, Account) and notification.data.error == 'Authentication failed':
            if not self.authFailPopupShown:
                self.authFailPopupShown = True
                NSRunAlertPanel(u"Registration Error",
                    u"The account %s could not be registered because of an authentication error" % notification.sender.id,
                    u"OK", None, None)
                self.authFailPopupShown = False

    def _NH_SIPAccountRegistrationDidEnd(self, notification):
        try:
            position = self.accounts.index(notification.sender)
        except ValueError:
            return
        self.accounts[position].registration_state = 'ended'
        self.refreshAccountList()

    _NH_BonjourAccountWillRegister = _NH_SIPAccountWillRegister
    _NH_BonjourAccountRegistrationDidSucceed = _NH_SIPAccountRegistrationDidSucceed
    _NH_BonjourAccountRegistrationDidFail = _NH_SIPAccountRegistrationDidFail
    _NH_BonjourAccountRegistrationDidEnd = _NH_SIPAccountRegistrationDidEnd

    def _NH_AudioDevicesDidChange(self, notification):
        old_devices = notification.data.old_devices
        new_devices = notification.data.new_devices
        diff = set(new_devices).difference(set(old_devices))
        if diff:
            new_device = diff.pop()
            BlinkLogger().log_info(u"New device %s detected, checking if we should switch to it..." % new_device)
            self.switchAudioDevice(new_device)
        else:
            self.menuWillOpen_(self.devicesMenu)

    def _NH_DefaultAudioDeviceDidChange(self, notification):
        self.menuWillOpen_(self.devicesMenu)

    def _NH_BonjourAccountDidAddNeighbour(self, notification):
        neighbour = notification.data.neighbour
        display_name = notification.data.display_name
        host = notification.data.host
        uri = notification.data.uri
        BlinkLogger().log_info(u"Discovered new Bonjour neighbour: %s %s" % (display_name, uri))
        self.model.bonjourgroup.addBonjourNeighbour(neighbour, str(uri), '%s (%s)' % (display_name or 'Unknown', host))
        self.contactOutline.reloadData()
        self.searchContacts()

    def _NH_BonjourAccountDidUpdateNeighbour(self, notification):
        neighbour = notification.data.neighbour
        display_name = notification.data.display_name
        host = notification.data.host
        uri = notification.data.uri
        BlinkLogger().log_info(u"Bonjour neighbour did change: %s %s" % (display_name, uri))
        self.model.bonjourgroup.updateBonjourNeighbour(neighbour, str(uri), '%s (%s)' % (display_name or 'Unknown', host))
        self.refreshContactsList()
        self.searchContacts()

    def _NH_BonjourAccountDidRemoveNeighbour(self, notification):
        BlinkLogger().log_info(u"Bonjour neighbour removed: %s" % notification.data.neighbour.name)
        self.model.bonjourgroup.removeBonjourNeighbour(notification.data.neighbour)
        self.contactOutline.reloadData()
        self.searchContacts()

    def _NH_MediaStreamDidInitialize(self, notification):
        if notification.sender.type == "audio":
            self.updateAudioButtons()

    def _NH_MediaStreamDidEnd(self, notification):
        if notification.sender.type == "audio":
            self.updateAudioButtons()

    def _NH_SIPApplicationDidStart(self, notification):
        settings = SIPSimpleSettings()
        if settings.service_provider.name:
            window_title =  "%s by %s" % (NSApp.delegate().applicationName, settings.service_provider.name)
            self.window().setTitle_(window_title)

    def _NH_BlinkMuteChangedState(self, notification):
        if self.backend.is_muted():
            self.muteButton.setState_(NSOnState)
            self.muteButton.setImage_(NSImage.imageNamed_("muted"))
        else:
            self.muteButton.setState_(NSOffState)
            self.muteButton.setImage_(NSImage.imageNamed_("mute"))

    def _NH_BlinkChatWindowClosed(self, notification):
        # TODO: avoid opening drawer if no audio session is connected -adi
        self.showAudioDrawer()

    def _NH_BlinkContactsHaveChanged(self, notification):
        self.refreshContactsList()

    def newAudioDeviceTimeout_(self, timer):
        NSApp.stopModalWithCode_(NSAlertAlternateReturn)

    def switchAudioDevice(self, device):
        hasAudio = any(sess.hasStreamOfType("audio") for sess in self.sessionControllers)
        if hasAudio:
            BlinkLogger().log_info(u"We have active sessions, switching input/output devices to %s" % device)
            settings = SIPSimpleSettings()
            settings.audio.input_device = unicode(device)
            settings.audio.output_device = unicode(device)
            settings.save()
        else:
            panel = NSGetInformationalAlertPanel("New Audio Device",
                    "Audio device %s has been plugged-in. Would you like to switch to it?" % device,
                    "Switch", "Ignore", None)
            timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(7, self, "newAudioDeviceTimeout:", panel, False)
            NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSModalPanelRunLoopMode)
            NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSDefaultRunLoopMode)
            session = NSApp.beginModalSessionForWindow_(panel)
            while True:
                ret = NSApp.runModalSession_(session)
                if ret != NSRunContinuesResponse:
                    break
            NSApp.endModalSession_(session)
            panel.close()
            NSReleaseAlertPanel(panel)

            if ret == NSAlertDefaultReturn:
                BlinkLogger().log_info(u"Switching input/output devices to %s" % device)
                settings = SIPSimpleSettings()
                settings.audio.input_device = unicode(device)
                settings.audio.output_device = unicode(device)
                settings.save()

        self.menuWillOpen_(self.devicesMenu)

    def _NH_BlinkSessionChangedState(self, notification):
        sender = notification.sender
        if sender.ended:
            self.sessionControllers.remove(sender)
        else:
            if sender not in self.sessionControllers:
                self.sessionControllers.append(sender)
        self.updatePresenceStatus()

    def _NH_BlinkConferenceGotUpdate(self, notification):
        self.updateParticipantsView()

    def _NH_ActiveAudioSessionChanged(self, notification):
        self.updateParticipantsView()

    def _NH_BlinkStreamHandlersChanged(self, notification):
        self.updatePresenceStatus()

    def _NH_CFGSettingsObjectDidChange(self, notification):
        settings = SIPSimpleSettings()
        if notification.data.modified.has_key("audio.silent"):
            if self.backend.is_silent():
                self.silentButton.setImage_(NSImage.imageNamed_("belloff"))
                self.silentButton.setState_(NSOnState)
            else:
                self.silentButton.setImage_(NSImage.imageNamed_("bellon"))
                self.silentButton.setState_(NSOffState)
        if notification.data.modified.has_key("service_provider.name"):
            if settings.service_provider.name:
                window_title =  "%s by %s" % (NSApp.delegate().applicationName, settings.service_provider.name)
                self.window().setTitle_(window_title)
            else:
                self.window().setTitle_(NSApp.delegate().applicationName)
        if isinstance(notification.sender, (Account, BonjourAccount)) and 'order' in notification.data.modified:
            self.refreshAccountList()

    def showAudioSession(self, streamController):
        self.sessionListView.addItemView_(streamController.view)
        self.updateAudioButtons()
        streamController.view.setSelected_(True)

        if not streamController.sessionController.hasStreamOfType("chat") and not streamController.sessionController.hasStreamOfType("video"):
            self.window().performSelector_withObject_afterDelay_("makeFirstResponder:", streamController.view, 0.5)
            self.showWindow_(None)
            self.showAudioDrawer()

    def showAudioDrawer(self):
        count = self.sessionListView.numberOfItems()
        if not self.drawer.isOpen() and count > 0:
            #self.drawer.setContentSize_(self.window().frame().size)
            self.drawer.open()

    def shuffleUpAudioSession(self, audioSessionView):
        # move up the given view in the audio session list so that it is after
        # all other conferenced sessions already at the top and before anything else
        last = None
        found = False
        for v in self.sessionListView.subviews():
            last = v
            if not v.conferencing:
                found = True
                break
            else:
                v.setNeedsDisplay_(True)
        if found and last != audioSessionView:
            audioSessionView.retain()
            audioSessionView.removeFromSuperview()
            self.sessionListView.insertItemView_before_(audioSessionView, last)
            audioSessionView.release()
            audioSessionView.setNeedsDisplay_(True)

    def shuffleDownAudioSession(self, audioSessionView):
        # move down the given view in the audio session list so that it is after
        # all other conferenced sessions
        audioSessionView.retain()
        audioSessionView.removeFromSuperview()
        self.sessionListView.addItemView_(audioSessionView)
        audioSessionView.release()

    def addAudioSessionToConference(self, stream):
        if self.conference is None:
            self.conference = AudioConference()
            BlinkLogger().log_info(u"Audio conference started")

        self.conference.add(stream.stream)

        stream.view.setConferencing_(True)
        subviews = self.sessionListView.subviews()
        selected = subviews.count() > 0 and subviews.objectAtIndex_(0).selected
        self.shuffleUpAudioSession(stream.view)
        self.conferenceButton.setState_(NSOnState)
        stream.view.setSelected_(True)

    def removeAudioSessionFromConference(self, stream):
        # if we're in a conference and the session is selected, then select back the conference
        # after removing
        wasSelected = stream.view.selected
        self.conference.remove(stream.stream)
        stream.view.setConferencing_(False)
        self.shuffleDownAudioSession(stream.view)

        count = 0
        for session in self.sessionControllers:
            if session.hasStreamOfType("audio"):
                s = session.streamHandlerOfType("audio")
                if s.isConferencing:
                    if count == 0: # we're the 1st one
                        if not s.view.selected and wasSelected:
                            # force select back of conference
                            s.view.setSelected_(True)
                    count += 1
        if count < 2 and not self.disbandingConference:
            self.disbandConference()

    def holdConference(self):
        if self.conference is not None:
            self.conference.hold()

    def unholdConference(self):
        if self.conference is not None:
            self.conference.unhold()

    def disbandConference(self):
        self.disbandingConference = True
        for session in self.sessionControllers:
            if session.hasStreamOfType("audio"):
                stream = session.streamHandlerOfType("audio")
                if stream.isConferencing:
                    stream.removeFromConference()
        self.conference = None
        self.disbandingConference = False
        self.conferenceButton.setState_(NSOffState)
        BlinkLogger().log_info(u"Audio conference ended")

    def finalizeSession(self, streamController):
        if streamController.isConferencing and self.conference is not None:
            self.removeAudioSessionFromConference(streamController)

        self.sessionListView.removeItemView_(streamController.view)
        self.updateAudioButtons()
        count = self.sessionListView.numberOfItems()
        if self.drawer.isOpen() and count == 0:
            self.drawer.close()

    def updateAudioButtons(self):
        c = self.sessionListView.subviews().count()
        cview = self.drawer.contentView()
        hangupAll = cview.viewWithTag_(10)
        conference = cview.viewWithTag_(11)
        hangupAll.setEnabled_(c > 0)

        # number of sessions that can be conferenced
        c = sum(s and 1 or 0 for s in self.sessionControllers if s.hasStreamOfType("audio") and s.streamHandlerOfType("audio").canConference)
        conference.setEnabled_(c > 1)

    def updatePresenceStatus(self):
        # check if there are any active voice sessions
        hasAudio = any(sess.hasStreamOfType("audio") for sess in self.sessionControllers)

        status = self.statusPopUp.selectedItem().representedObject()
        if status == "phone":
            if not hasAudio and self.originalPresenceStatus:
                i = self.statusPopUp.indexOfItemWithRepresentedObject_(self.originalPresenceStatus)
                self.statusPopUp.selectItemAtIndex_(i)
                self.originalPresenceStatus = None
        elif status != "phone":
            if hasAudio:
                i = self.statusPopUp.indexOfItemWithRepresentedObject_("phone")
                self.statusPopUp.selectItemAtIndex_(i)
                self.originalPresenceStatus = status
        # TODO Status -> Presence activity menu must be updated too -adi

    def updateActionButtons(self):
        tabItem = self.mainTabView.selectedTabViewItem().identifier()
        audioOk = False
        chatOk = False
        desktopOk = False
        account = self.activeAccount()
        contacts = self.getSelectedContacts()
        if account is not None:
            if tabItem == "contacts":
                audioOk = len(contacts) > 0
                if contacts and account is BonjourAccount() and not is_full_sip_uri(contacts[0].uri):
                    chatOk = False
                else:
                    chatOk = audioOk
                if contacts and not is_full_sip_uri(contacts[0].uri):
                    desktopOk = False
                else:
                    desktopOk = audioOk
            elif tabItem == "search":
                audioOk = self.searchBox.stringValue().strip() != u""
                chatOk = audioOk
                desktopOk = audioOk
            elif tabItem == "dialpad":
                audioOk = self.searchBox.stringValue().strip() != u""
                chatOk = audioOk

        self.actionButtons.setEnabled_forSegment_(audioOk, 0)
        self.actionButtons.setEnabled_forSegment_(chatOk and self.backend.isMediaTypeSupported('chat'), 1)
        self.actionButtons.setEnabled_forSegment_(desktopOk and self.backend.isMediaTypeSupported('desktop-sharing'), 2)

        c = sum(s and 1 or 0 for s in self.sessionControllers if s.hasStreamOfType("audio") and s.streamHandlerOfType("audio").canConference)
        self.addContactToConferenceDialPad.setEnabled_(True if ((self.isJoinConferenceWindowOpen() or self.isAddParticipantsWindowOpen() or c > 0)) and self.searchBox.stringValue().strip()!= u"" else False)

    def isJoinConferenceWindowOpen(self):
        return any(window for window in NSApp().windows() if window.title() == 'Join Conference' and window.isVisible())

    def isAddParticipantsWindowOpen(self):
        return any(window for window in NSApp().windows() if window.title() == 'Add Participants' and window.isVisible())

    def getContactMatchingURI(self, uri):
        return self.model.getContactMatchingURI(uri)

    def hasContactMatchingURI(self, uri):
        return self.model.hasContactMatchingURI(uri)

    def iconPathForURI(self, uri):
        if AccountManager().has_account(uri):
            return self.iconPathForSelf()
        contact = self.getContactMatchingURI(uri)
        if contact:
            path = contact.iconPath()
            if os.path.isfile(path):
                return path
        return contactIconPathForURI("default_user_icon")

    def iconPathForSelf(self):
        icon = NSUserDefaults.standardUserDefaults().stringForKey_("PhotoPath")
        if not icon or not os.path.exists(unicode(icon)):
            return contactIconPathForURI("default_user_icon")
        return unicode(icon)

    def addContact(self, uri, display_name=None):
        self.model.addNewContact(uri, display_name=display_name)
        self.contactOutline.reloadData()

    @objc.IBAction
    def accountSelectionChanged_(self, sender):
        account = sender.selectedItem().representedObject()
        if account:
            name = format_identity_simple(account)
            self.nameText.setStringValue_(name)
            AccountManager().default_account = account

            if account is BonjourAccount():
                self.model.moveBonjourGroupFirst()
                self.contactOutline.reloadData()
                # select the Bonjour stuff group and expand it
                self.contactOutline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(0), False)
                if not self.model.bonjourgroup.expanded:
                    self.contactOutline.expandItem_(self.model.bonjourgroup)
                    self.model.bonjourgroup.expanded = False
                # guess how many rows fit in the outline
                maxRows = NSHeight(self.contactOutline.frame()) / 30
                # scroll 1st row of bonjour group to visible
                self.contactOutline.scrollRowToVisible_(0)
            elif self.model.bonjourgroup in self.model.contactGroupsList and self.model.contactGroupsList.index(self.model.bonjourgroup) == 0:
                self.model.restoreBonjourGroupPosition()
                self.contactOutline.reloadData()
                if not self.model.bonjourgroup.expanded:
                    self.contactOutline.collapseItem_(self.model.bonjourgroup)
        else:
            # select back the account and open the new account wizard
            i = sender.indexOfItemWithRepresentedObject_(AccountManager().default_account)
            sender.selectItemAtIndex_(i)
            enroll = EnrollmentController.alloc().init()
            enroll.setupForAdditionalAccounts()
            enroll.runModal()
            self.refreshAccountList()

    def contactSelectionChanged_(self, notification):
        self.updateActionButtons()
        readonly = any((getattr(c, "editable", None) is False or getattr(c, "dynamic", None) is True) for c in self.getSelectedContacts(True))

        self.contactsMenu.itemWithTag_(31).setEnabled_(not readonly and len(self.getSelectedContacts(includeGroups=False)) > 0)
        self.contactsMenu.itemWithTag_(32).setEnabled_(not readonly and len(self.getSelectedContacts(includeGroups=True)) > 0)
        self.contactsMenu.itemWithTag_(33).setEnabled_(not readonly)
        self.contactsMenu.itemWithTag_(34).setEnabled_(not readonly)

    def contactGroupCollapsed_(self, notification):
        group = notification.userInfo()["NSObject"]
        group.expanded = False

    def contactGroupExpanded_(self, notification):
        group = notification.userInfo()["NSObject"]
        group.expanded = True
        if group.special == "addressbook":
            group.loadAddressBook()

    @objc.IBAction
    def backToContacts_(self, sender):
        self.mainTabView.selectTabViewItemWithIdentifier_("contacts")
        self.resetWidgets()

    @objc.IBAction
    def clearSearchField_(self, sender):
        self.resetWidgets()

    def resetWidgets(self):
        self.searchBox.setStringValue_("")
        self.addContactToConferenceDialPad.setEnabled_(False)
        self.addContactButtonDialPad.setEnabled_(False)
        self.updateActionButtons()

    @objc.IBAction
    def addGroup_(self, sender):
        self.model.addNewGroup()
        self.refreshContactsList()
        self.searchContacts()

    @objc.IBAction
    def joinConferenceClicked_(self, sender):
        account = self.activeAccount()
        conference = self.showJoinConferenceWindow(default_domain=account.id.domain)
        if conference is not None:
            self.joinConference(conference.target, conference.media_types, conference.participants)

    def showJoinConferenceWindow(self, target=None, participants=None, media=None, default_domain=None):
        self.joinConferenceWindow = JoinConferenceWindowController(target=target, participants=participants, media=media, default_domain=default_domain)
        conference = self.joinConferenceWindow.run()
        return conference

    def showAddParticipantsWindow(self, target=None, default_domain=None):
        self.addParticipantsWindow = AddParticipantsWindowController(target=target, default_domain=default_domain)
        participants = self.addParticipantsWindow.run()
        return participants

    @objc.IBAction
    def addContact_(self, sender):
        if sender != self.addContactButton:
            contact = self.model.addNewContact(self.searchBox.stringValue())

            if contact:
                self.resetWidgets()
                self.refreshContactsList()
                self.searchContacts()

                row = self.contactOutline.rowForItem_(contact)
                if row != NSNotFound:
                    self.contactOutline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)
                    self.contactOutline.scrollRowToVisible_(row)
                    self.window().makeFirstResponder_(self.contactOutline)
        else:
            item = self.contactOutline.itemAtRow_(self.contactOutline.selectedRow())
            if type(item) == BlinkContact:
                group = self.contactOutline.parentForItem_(item)
            else:
                group = item
            contact = self.model.addNewContact(group=group.name if group and not group.dynamic else None)
            if contact:
                self.refreshContactsList()
                self.searchContacts()

                row = self.contactOutline.rowForItem_(contact)
                if row != -1:
                    self.contactOutline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)
                    self.contactOutline.scrollRowToVisible_(row)
                    self.window().makeFirstResponder_(self.contactOutline)

    @objc.IBAction
    def editContact_(self, sender):
        try:
            contact = self.getSelectedContacts()[0]
        except IndexError:
            self.renameGroup_(sender)
        else:
            self.model.editContact(contact)
            self.refreshContactsList()
            self.searchContacts()

    @objc.IBAction
    def deleteContact_(self, sender):
        for contact in self.getSelectedContacts() or ():
            self.model.deleteContact(contact)
            self.refreshContactsList()
            self.searchContacts()

    @objc.IBAction
    def renameGroup_(self, sender):
        row = self.contactOutline.selectedRow()
        if row >= 0:
            item = self.contactOutline.itemAtRow_(row)
            if isinstance(item, BlinkContact):
                group = self.contactOutline.parentForItem(item)
            else:
                group = item
            self.model.editGroup(group)
            self.refreshContactsList()
            self.searchContacts()

        #row = self.contactOutline.selectedRow()
        #if row < 0:
        #    return
        #row = self.contactOutline.rowForItem_(self.contactOutline.parentForItem_(self.contactOutline.itemAtRow_(row)))
        #self.contactOutline.editColumn_row_withEvent_select_(0, row, None, True)

    @objc.IBAction
    def deleteGroup_(self, sender):
        row = self.contactOutline.selectedRow()
        if row >= 0:
            item = self.contactOutline.itemAtRow_(row)
            if isinstance(item, BlinkContact):
                group = self.contactOutline.parentForItem(item)
            else:
                group = item
            self.model.deleteContact(group)
            self.refreshContactsList()

    @objc.IBAction
    def silentClicked_(self, sender):
        self.backend.silent(not self.backend.is_silent())

    @objc.IBAction
    def muteClicked_(self, sender):
        if sender != self.muteButton:
            if self.backend.is_muted():
                self.muteButton.setState_(NSOffState)
            else:
                self.muteButton.setState_(NSOnState)
        if self.muteButton.state() == NSOnState:
            self.backend.mute(True)
            self.muteButton.setImage_(NSImage.imageNamed_("muted"))
        else:
            self.backend.mute(False)
            self.muteButton.setImage_(NSImage.imageNamed_("mute"))

        NotificationCenter().post_notification("BlinkMuteChangedState", sender=self)

    @objc.IBAction
    def toggleAnsweringMachine_(self, sender):
        settings = SIPSimpleSettings()
        settings.answering_machine.enabled = not settings.answering_machine.enabled
        settings.save()

    @objc.IBAction
    def toggleAutoAccept_(self, sender):
        settings = SIPSimpleSettings()
        if sender.tag() == 51: # Chat
            settings.chat.auto_accept = not settings.chat.auto_accept
            settings.save()
        elif sender.tag() == 52: # Files
            settings.file_transfer.auto_accept = not settings.file_transfer.auto_accept
            settings.save()
        elif sender.tag() == 53: # Bonjour Audio
            account = BonjourAccount()
            account.audio.auto_accept = not account.audio.auto_accept
            account.save()

    @objc.IBAction
    def searchContacts_(self, sender):
        if sender == self.searchBox:
            text = unicode(self.searchBox.stringValue()).strip()
            event = NSApp.currentEvent()

            if self.mainTabView.selectedTabViewItem().identifier() == "dialpad":
                self.addContactButtonDialPad.setEnabled_(True if text != u"" else False)

                new_value = ""
                for l in unicode(self.searchBox.stringValue().strip()):
                    new_value = new_value + translate_alpha2digit(l)
                else:
                    self.searchBox.setStringValue_(new_value)
                    if event.type() == NSKeyUp:
                        key = translate_alpha2digit(str(event.characters()))
                        if key in string.digits:
                            self.play_dtmf(key)

            if text != u"" and event.type() == NSKeyDown and event.characters() == u"\r":
                try:
                    text = unicode(text)
                except:
                    NSRunAlertPanel(u"Invalid URI", u"The supplied URI contains invalid characters", u"OK", None, None)
                    return
                else:
                    _split = text.split(';')
                    _text = []
                    for item in _split[:]:
                        if not item.startswith("session-type"):
                            _text.append(item)
                            _split.remove(item)
                    text = ";".join(_text)
                    try:
                        session_type = _split[0].split("=")[1]
                    except IndexError:
                        session_type = None

                    self.resetWidgets()
                    self.startSessionWithSIPURI(text, session_type)

            self.searchContacts()

    def searchContacts(self):
        if self.mainTabView.selectedTabViewItem().identifier() == "dialpad":
            self.updateActionButtons()
            return

        text = self.searchBox.stringValue().strip()
        if text == u"":
            self.mainTabView.selectTabViewItemWithIdentifier_("contacts")
        else:
            self.contactOutline.deselectAll_(None)
            self.mainTabView.selectTabViewItemWithIdentifier_("search")
        self.updateActionButtons()
        self.searchResultsModel.contactGroupsList = [contact for group in self.model.contactGroupsList for contact in group.contacts if text in contact]

        active_account = self.activeAccount()
        input_text = '%s@%s' % (text, active_account.id.domain) if active_account is not BonjourAccount() and "@" not in text else text
        input_contact = BlinkContact(input_text, name=unicode(input_text))
        exists = text in (contact.uri for contact in self.searchResultsModel.contactGroupsList)

        if not exists:
            self.searchResultsModel.contactGroupsList.append(input_contact)

        self.addContactButtonSearch.setEnabled_(not exists)
        self.searchOutline.reloadData()


    @objc.IBAction
    def addContactToConference_(self, sender):
        active_sessions = [s for s in self.sessionControllers if s.hasStreamOfType("audio") and s.streamHandlerOfType("audio").canConference]

        if self.mainTabView.selectedTabViewItem().identifier() == "dialpad":
            target = unicode(self.searchBox.stringValue()).strip()
            if not target:
                return
        else:
            try:
                contact = self.getSelectedContacts()[0]
            except IndexError:
                target = unicode(self.searchBox.stringValue()).strip()
                if not target:
                    return
            else:
                target = contact.uri

        self.resetWidgets()

        if self.isJoinConferenceWindowOpen():
            self.joinConferenceWindow.addParticipant(target)
        elif self.isAddParticipantsWindowOpen():
            self.addParticipantsWindow.addParticipant(target)
        elif active_sessions:
            # start conference with active audio sessions
            for s in active_sessions:
                handler = s.streamHandlerOfType("audio")
                handler.view.setConferencing_(True)

            session = self.startSessionWithSIPURI(target, "audio")
            handler = session.streamHandlerOfType("audio")
            handler.view.setConferencing_(True)
            handler.addToConference()
            for s in active_sessions:
                handler = s.streamHandlerOfType("audio")
                handler.addToConference()

    def closeAllSessions(self):
        for session in self.sessionControllers[:]:
            session.end()

    def startSessionToSelectedContact(self, media):
        # activate the app in case the app is not active
        NSApp.activateIgnoringOtherApps_(True)

        account = self.activeAccount()
        if not account:
            NSRunAlertPanel(u"Cannot Initiate Session", u"There are currently no active SIP accounts", u"OK", None, None)
            return

        try:
            contact = self.getSelectedContacts()[0]
        except IndexError:
            target = unicode(self.searchBox.stringValue()).strip()
            if not target:
                return
            display_name = ''
        else:
            target = contact.uri
            display_name = contact.display_name

        target = self.backend.parse_sip_uri(target, account)
        if not target:
            return

        if contact in self.model.bonjourgroup.contacts:
            account = BonjourAccount()

        session = SessionController.alloc().initWithAccount_target_displayName_(account, target, unicode(display_name))
        session.setOwner_(self)
        self.sessionControllers.append(session)

        if media == "desktop-sharing":
            media = ("desktop-sharing", "audio")

        if media == "video":
            media = ("video", "audio")

        if type(media) is not tuple:
            if not session.startSessionWithStreamOfType(media):
                BlinkLogger().log_error(u"Failed to start session with stream of type %s" % media)
        else:
            if not session.startCompositeSessionWithStreamsOfTypes(media):
                BlinkLogger().log_error(u"Failed to start session with streams of types %s" % str(media))

    def startSessionWithAccount(self, account, target, media):
        # activate the app in case the app is not active
        NSApp.activateIgnoringOtherApps_(True)
        if not account:
            NSRunAlertPanel(u"Cannot Initiate Session", u"There are currently no active SIP accounts", u"OK", None, None)
            return

        target_uri = self.backend.parse_sip_uri(target, account)
        if not target_uri:
            return

        contact = self.getContactMatchingURI(target_uri)
        display_name = contact.display_name if contact else ''

        session = SessionController.alloc().initWithAccount_target_displayName_(account, target_uri, unicode(display_name))
        session.setOwner_(self)
        self.sessionControllers.append(session)

        if type(media) is not tuple:
            if not session.startSessionWithStreamOfType(media):
                BlinkLogger().log_error(u"Failed to start session with stream of type %s" % media)
        else:
            if not session.startCompositeSessionWithStreamsOfTypes(media):
                BlinkLogger().log_error(u"Failed to start session with streams of types %s" % str(media))


    def startSessionWithSIPURI(self, text, session_type="audio"):
        account = self.activeAccount()
        if not account:
            NSRunAlertPanel(u"Cannot Initiate Session", u"There are currently no active SIP accounts",
                            "OK", None, None)
            return None
        if not text:
            return None

        target_uri = self.backend.parse_sip_uri(text, account)
        if target_uri:
            session = SessionController.alloc().initWithAccount_target_displayName_(account, target_uri, None)
            self.sessionControllers.append(session)
            session.setOwner_(self)
            if session_type == "audio":
                session.startAudioSession()
            elif session_type == "chat":
                session.startChatSession()
            else:
                session.startAudioSession()
            return session
        else:
            print "Error parsing URI %s"%text
            return None

    def joinConference(self, target, media, participants=[]):
        # activate the app in case the app is not active
        NSApp.activateIgnoringOtherApps_(True)
        account = self.activeAccount()
        if not account:
            NSRunAlertPanel(u"Cannot Initiate Session", u"There are currently no active SIP accounts", u"OK", None, None)
            return

        target = self.backend.parse_sip_uri(target, account)
        if not target:
            return

        session = SessionController.alloc().initWithAccount_target_displayName_(account, target, unicode(target))
        session.setOwner_(self)
        self.sessionControllers.append(session)

        if participants:
            # Add invited participants to the drawer
            session.mustShowDrawer = True
            for uri in participants:
                contact = self.getContactMatchingURI(uri)
                if contact:
                    contact = BlinkContact(uri, name=contact.name, icon=contact.icon)
                else:
                    contact = BlinkContact(uri=uri, name=uri)
                contact.setDetail('Invitation sent...')
                session.invited_participants.append(contact)
                session.participants_log.add(uri)

        if type(media) is not tuple:
            if not session.startSessionWithStreamOfType(media):
                BlinkLogger().log_error(u"Failed to start session with stream of type %s" % media)
        else:
            if not session.startCompositeSessionWithStreamsOfTypes(media):
                BlinkLogger().log_error(u"Failed to start session with streams of types %s" % str(media))

    @objc.IBAction
    def startAudioToSelected_(self, sender):
        self.startSessionToSelectedContact("audio")

    @objc.IBAction
    def startVideoToSelected_(self, sender):
        self.startSessionToSelectedContact("video")

    @objc.IBAction
    def startChatToSelected_(self, sender):
        self.startSessionToSelectedContact("chat")

    @objc.IBAction
    def sendSMSToSelected_(self, sender):
        account = self.activeAccount()
        if not account:
            NSRunAlertPanel(u"Cannot Send SMS", u"There are currently no active SIP accounts", u"OK", None, None)
            return

        try:
            contact = self.getSelectedContacts()[0]
        except IndexError:
            target = unicode(self.searchBox.stringValue()).strip()
            if not target:
                return
            display_name = ''
        else:
            target = contact.uri
            display_name = contact.display_name

        if contact in self.model.bonjourgroup.contacts:
            account = BonjourAccount()

        target = self.backend.parse_sip_uri(target, account)
        if not target:
            return

        try:
            NSApp.activateIgnoringOtherApps_(True)
            SMSWindowManager.SMSWindowManager().openMessageWindow(target, display_name, account)
        except:
            import traceback
            traceback.print_exc()

    @objc.IBAction
    def startDesktopToSelected_(self, sender):
        if sender:
            tag = sender.tag()
            if tag == 1:
                self.startSessionToSelectedContact(("desktop-viewer", "audio"))
            elif tag == 2:
                self.startSessionToSelectedContact(("desktop-server", "audio"))
            elif tag == 5:
                self.startSessionToSelectedContact("desktop-viewer")
            elif tag == 6:
                self.startSessionToSelectedContact("desktop-server")
        else:
            self.startSessionToSelectedContact("desktop-sharing")

    @objc.IBAction
    def actionButtonClicked_(self, sender):
        account = self.activeAccount()
        if not account:
            NSRunAlertPanel(u"Cannot Initiate Session", u"There are currently no active SIP accounts", u"OK", None, None)
            return

        if self.mainTabView.selectedTabViewItem().identifier() == "dialpad":
            target = unicode(self.searchBox.stringValue()).strip()
            if not target:
                return

            self.startSessionWithSIPURI(target)
            self.searchBox.setStringValue_(u"")
            self.addContactToConferenceDialPad.setEnabled_(False)
        else:
            media = None
            try:
                contact = self.getSelectedContacts()[0]
            except IndexError:
                return
            if sender == self.contactOutline or sender == self.searchOutline:
                if contact.preferred_media == "chat":
                    media = "chat"
                else:
                    media = "audio"
            elif sender.selectedSegment() == 1:
                # IM button
                point = sender.convertPointToBase_(NSZeroPoint)
                point.x += sender.widthForSegment_(0)
                point.y -= NSHeight(sender.frame())
                event = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                                NSLeftMouseUp, point, 0, NSDate.timeIntervalSinceReferenceDate(), sender.window().windowNumber(),
                                sender.window().graphicsContext(), 0, 1, 0)
                NSMenu.popUpContextMenu_withEvent_forView_(self.chatMenu, event, sender)
                return
            elif sender.selectedSegment() == 2:
                # DS button
                point = sender.convertPointToBase_(NSZeroPoint)
                point.x += sender.widthForSegment_(0) + sender.widthForSegment_(1)
                point.y -= NSHeight(sender.frame())
                event = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                                NSLeftMouseUp, point, 0, NSDate.timeIntervalSinceReferenceDate(), sender.window().windowNumber(),
                                sender.window().graphicsContext(), 0, 1, 0)
                NSMenu.popUpContextMenu_withEvent_forView_(self.desktopShareMenu, event, sender)
                return
            else:
                media = "audio"

            self.startSessionToSelectedContact(media)

    @objc.IBAction
    def sessionButtonClicked_(self, sender):
        sessionController = self.sessionListModel.sessions[sender.selectedRow()]
        cell= sender.preparedCellAtColumn_row_(1, sender.selectedRow())
        if cell.selectedSegment() == 0:
            sessionController.toggleHold()
        else:
            sessionController.end()

    @objc.IBAction
    def hangupAllClicked_(self, sender):
        for session in self.sessionControllers:
            if session.hasStreamOfType("audio"):
                if len(session.streamHandlers) == 1:
                    session.end()
                elif session.hasStreamOfType("desktop-sharing") and len(session.streamHandlers) == 2:
                    session.end()
                else:
                    stream = session.streamHandlerOfType("audio")
                    stream.end()

    @objc.IBAction
    def conferenceClicked_(self, sender):
        count = sum(s and 1 or 0 for s in self.sessionControllers if s.hasStreamOfType("audio") and s.streamHandlerOfType("audio").canConference)

        if self.conferenceButton.state() == NSOnState:
            if count < 2:
                self.conferenceButton.setState_(NSOffState)
                return
            # if conference already started:
            #    return

            if NSRunAlertPanel("Audio Conference", "Would you like to start a conference with the %i active sessions?"%count,
                            "OK", "Cancel", "") != NSAlertDefaultReturn:
                self.conferenceButton.setState_(NSOffState)
                return

            conference_streams = []
            for session in self.sessionControllers:
                if session.hasStreamOfType("audio"):
                    stream = session.streamHandlerOfType("audio")
                    if stream.canConference:
                        stream.view.setConferencing_(True)
                        conference_streams.append(stream)

            for stream in conference_streams:
                stream.addToConference()
        else:
            # if not conference already started:
            #   return
            self.disbandConference()

    @objc.IBAction
    def showHistoryViewer_(self, sender):
        if NSApp.delegate().applicationName != 'Blink Lite':
            if not self.historyViewer:
                self.historyViewer = HistoryViewer()
            self.historyViewer.showWindow_(None)

    @objc.IBAction
    def toggleAudioSessionsDrawer_(self, sender):
        self.drawer.toggle_(sender)
        if self.drawer.isOpen():
            sessionBoxes = self.sessionListView.subviews()
            if sessionBoxes.count() > 0:
                selected = [session for session in sessionBoxes if session.selected]
                if selected:
                    self.window().makeFirstResponder_(selected[0])
                else:
                    self.window().makeFirstResponder_(sessionBoxes.objectAtIndex_(0))

    def sip_error(self, message):
        NSRunAlertPanel("Error", message, "OK", None, None)

    def sip_warning(self, message):
        NSRunAlertPanel("Warning", message, "OK", None, None)

    def handle_incoming_session(self, session, streams):
        settings = SIPSimpleSettings()
        stream_type_list = list(set(stream.type for stream in streams))

        if self.model.hasContactMatchingURI(session.remote_identity.uri):
            if settings.chat.auto_accept and stream_type_list == ['chat']:
                BlinkLogger().log_info(u"Automatically accepting chat session from %s" % session.remote_identity)
                self.startIncomingSession(session, streams)
                return
            elif settings.file_transfer.auto_accept and stream_type_list == ['file-transfer']:
                BlinkLogger().log_info(u"Automatically accepting file transfer from %s" % session.remote_identity)
                self.startIncomingSession(session, streams)
                return
        elif session.account is BonjourAccount() and stream_type_list == ['chat']:
                BlinkLogger().log_info(u"Automatically accepting Bonjour chat session from %s" % session.remote_identity)
                self.startIncomingSession(session, streams)
                return
        try:
            session.send_ring_indication()
        except IllegalStateError, e:
            BlinkLogger().log_error(u"IllegalStateError: %s" % e)
        else:
            if settings.answering_machine.enabled and settings.answering_machine.answer_delay == 0:
                self.startIncomingSession(session, [s for s in streams if s.type=='audio'], answeringMachine=True)
            else:
                sessionController = SessionController.alloc().initWithSession_(session)
                sessionController.setOwner_(self)
                self.sessionControllers.append(sessionController)
                if not self.alertPanel:
                    self.alertPanel = AlertPanel.alloc().initWithOwner_(self)
                self.alertPanel.addIncomingSession(session)
                self.alertPanel.show()

    def handle_incoming_proposal(self, session, streams):
        settings = SIPSimpleSettings()
        stream_type_list = list(set(stream.type for stream in streams))

        if not self.backend.isProposedMediaTypeSupported(streams):
            BlinkLogger().log_info(u"Unsupported media type, proposal rejected")
            session.reject_proposal()
            return
        elif stream_type_list == ['chat'] and 'audio' in (s.type for s in session.streams):
            BlinkLogger().log_info(u"Automatically accepting chat for established audio session from %s" % session.remote_identity)
            self.acceptIncomingProposal(session, streams)
            return
        elif session.account is BonjourAccount():
            if stream_type_list == ['chat']:
                BlinkLogger().log_info(u"Automatically accepting Bonjour chat session from %s" % session.remote_identity)
                self.acceptIncomingProposal(session, streams)
                return
            elif 'audio' in stream_type_list and session.account.audio.auto_accept:
                session_manager = SessionManager()
                have_audio_call = any(s for s in session_manager.sessions if s is not session and s.streams and 'audio' in (stream.type for stream in s.streams))
                if not have_audio_call:
                    accepted_streams = [s for s in streams if s.type in ("audio", "chat")]
                    BlinkLogger().log_info(u"Automatically accepting Bonjour audio and chat session from %s" % session.remote_identity)
                    self.acceptIncomingProposal(session, accepted_streams)
                    return
        elif self.model.hasContactMatchingURI(session.remote_identity.uri):
            settings = SIPSimpleSettings()
            if settings.chat.auto_accept and stream_type_list == ['chat']:
                BlinkLogger().log_info(u"Automatically accepting chat session from %s" % session.remote_identity)
                self.acceptIncomingProposal(session, streams)
                return
            elif settings.file_transfer.auto_accept and stream_type_list == ['file-transfer']:
                BlinkLogger().log_info(u"Automatically accepting file transfer from %s" % session.remote_identity)
                self.acceptIncomingProposal(session, streams)
                return
        try:
            session.send_ring_indication()
        except IllegalStateError:
            BlinkLogger().log_error(u"IllegalStateError: %s" % e)
        else:
            if not self.alertPanel:
                self.alertPanel = AlertPanel.alloc().initWithOwner_(self)
            self.alertPanel.addIncomingStreamProposal(session, streams)
            self.alertPanel.show()

    def sip_session_missed(self, session, stream_types):
        BlinkLogger().log_info(u"Missed incoming session from %s" % session.remote_identity)
        if 'audio' in stream_types:
            NSApp.delegate().noteMissedCall()

    def sip_nat_detected(self, nat_type):
        BlinkLogger().log_info(u"Detected NAT Type: %s" % nat_type)

    def setCollapsed(self, flag):
        if self.loaded:
            self.collapsedState = flag
            self.updateParticipantsView()

    def windowWillUseStandardFrame_defaultFrame_(self, window, nframe):
        if self.originalSize:
            nframe = window.frame()
            nframe.size = self.originalSize
            nframe.origin.y -= nframe.size.height - window.frame().size.height
            self.originalSize = None
            self.setCollapsed(False)
        else:
            self.setCollapsed(True)
            self.originalSize = window.frame().size
            nframe = window.frame()
            nframe.origin.y += nframe.size.height - 154
            nframe.size.height = 154
            self.contactOutline.deselectAll_(None)
        return nframe

    def windowWillResize_toSize_(self, sender, size):
        if size.height == 157:
            size.height = 154
        return size

    def windowDidResize_(self, notification):
        if NSHeight(self.window().frame()) > 154:
            self.originalSize = None
            self.setCollapsed(False)
        else:
            self.contactOutline.deselectAll_(None)

        # make sure some controls are in their correct position after a resize of the window
        if self.notFoundTextOffset is not None:
            frame = self.notFoundText.frame()
            frame.origin.y = NSHeight(self.notFoundText.superview().frame()) - self.notFoundTextOffset
            self.notFoundText.setFrame_(frame)

            frame = self.searchOutline.enclosingScrollView().frame()
            if self.searchOutlineTopOffset:
                frame.size.height = NSHeight(self.searchOutline.enclosingScrollView().superview().frame()) - self.searchOutlineTopOffset
                self.searchOutline.enclosingScrollView().setFrame_(frame)


    def drawerDidOpen_(self, notification):
        windowMenu = NSApp.mainMenu().itemWithTag_(300).submenu()
        if self.collapsedState:
            self.window().zoom_(None)
            self.setCollapsed(True)

    def drawerDidClose_(self, notification):
        windowMenu = NSApp.mainMenu().itemWithTag_(300).submenu()
        if self.collapsedState:
            self.window().zoom_(None)
            self.setCollapsed(True)

    @objc.IBAction
    def showDebugWindow_(self, sender):
        self.debugWindow.show()

    @objc.IBAction
    def toggleMirrorWindow_(self, sender):
        if self.mirrorWindow.visible:
            self.mirrorWindow.hide()
        else:
            self.mirrorWindow.show()

    @objc.IBAction
    def presenceTextAction_(self, sender):
        if sender == self.nameText:
            name = unicode(self.nameText.stringValue())
            if self.activeAccount():
                self.activeAccount().display_name = name
                self.activeAccount().save()
            self.window().fieldEditor_forObject_(False, sender).setSelectedRange_(NSMakeRange(0, 0))
            self.window().makeFirstResponder_(self.contactOutline)
            sender.resignFirstResponder()
        elif sender == self.statusText:
            text = unicode(self.statusText.stringValue())
            self.window().fieldEditor_forObject_(False, sender).setSelectedRange_(NSMakeRange(0, 0))
            self.window().makeFirstResponder_(self.contactOutline)
            NSUserDefaults.standardUserDefaults().setValue_forKey_(text, "PresenceNote")

    @objc.IBAction
    def presentStatusChanged_(self, sender):
        value = sender.title()
        NSUserDefaults.standardUserDefaults().setValue_forKey_(value, "PresenceStatus")

        for item in self.presenceMenu.itemArray():
            item.setState_(NSOffState)
        item = self.presenceMenu.itemWithTitle_(value)
        item.setState_(NSOnState)

        menu = self.statusPopUp.menu()
        item = menu.itemWithTitle_(value)
        self.statusPopUp.selectItem_(item)

    @objc.IBAction
    def showHelp_(self, sender):
        if NSApp.delegate().applicationName == 'Blink Lite':
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_("http://icanblink.com/help-lite.phtml"))
        elif  NSApp.delegate().applicationName == 'Blink Pro':
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_("http://icanblink.com/help-pro.phtml"))
        else:
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_("http://icanblink.com/help.phtml"))

    def updateBlinkMenu(self):
        settings = SIPSimpleSettings()

        self.blinkMenu.itemWithTag_(1).setTitle_('About %s' % NSApp.delegate().applicationName)

        if NSApp.delegate().applicationName == 'Blink Pro':
            self.blinkMenu.itemWithTag_(2).setHidden_(True)
            self.blinkMenu.itemWithTag_(3).setHidden_(True)
            self.blinkMenu.itemWithTag_(8).setHidden_(True)
            self.blinkMenu.itemWithTag_(7).setHidden_(True)
        elif NSApp.delegate().applicationName == 'Blink Lite':
            self.blinkMenu.itemWithTag_(2).setHidden_(True)
            self.blinkMenu.itemWithTag_(3).setHidden_(True)
        else:
            self.blinkMenu.itemWithTag_(7).setHidden_(False)
            self.blinkMenu.itemWithTag_(8).setHidden_(False)

        if settings.service_provider.name:
            if settings.service_provider.about_url or settings.service_provider.help_url:
                self.blinkMenu.itemWithTag_(4).setHidden_(False)
            if settings.service_provider.about_url:
                title = 'About %s...' % settings.service_provider.name
                self.blinkMenu.itemWithTag_(5).setTitle_(title)
                self.blinkMenu.itemWithTag_(5).setHidden_(False)
            if settings.service_provider.help_url:
                title = '%s Support Page...' % settings.service_provider.name
                self.blinkMenu.itemWithTag_(6).setTitle_(title)
                self.blinkMenu.itemWithTag_(6).setHidden_(False)
        else:
            self.blinkMenu.itemWithTag_(4).setHidden_(True)
            self.blinkMenu.itemWithTag_(5).setHidden_(True)
            self.blinkMenu.itemWithTag_(6).setHidden_(True)


    def menuNeedsUpdate_(self, menu):
        item = menu.itemWithTag_(300) # mute
        if item:
            item.setState_(self.backend.is_muted() and NSOnState or NSOffState)
        item = menu.itemWithTag_(301) # silent
        if item:
            item.setState_(self.backend.is_silent() and NSOnState or NSOffState)

    def updateStatusMenu(self):
        settings = SIPSimpleSettings()

        item = self.statusMenu.itemWithTag_(50) # Answering machine
        item.setState_(settings.answering_machine.enabled and NSOnState or NSOffState)

        if NSApp.delegate().applicationName == 'Blink Lite':
            item.setEnabled_(False)
            item.setTitle_(u'Enable Answering Machine (Available in Blink Pro)')

        item = self.statusMenu.itemWithTag_(51) # chat
        item.setState_(settings.chat.auto_accept and NSOnState or NSOffState)
        item.setEnabled_(self.backend.isMediaTypeSupported('chat'))

        item = self.statusMenu.itemWithTag_(52) # file
        item.setState_(settings.file_transfer.auto_accept and NSOnState or NSOffState)
        item.setEnabled_(self.backend.isMediaTypeSupported('file-transfer'))

        item = self.statusMenu.itemWithTag_(54) # my video
        item.setState_(self.mirrorWindow.visible and NSOnState or NSOffState)
        item.setEnabled_(False) # TODO: enable video -adi

    def updateToolsMenu(self):
        account = self.activeAccount()

        item = self.toolsMenu.itemWithTag_(40) # Settings on SIP server
        item.setEnabled_(bool(not isinstance(account, BonjourAccount) and self.activeAccount().server.settings_url))

        item = self.toolsMenu.itemWithTag_(41) # Search Directory...
        item.setEnabled_(bool(not isinstance(account, BonjourAccount) and self.activeAccount().server.settings_url))

        item = self.toolsMenu.itemWithTag_(42) # Call History
        item.setEnabled_(bool(not isinstance(account, BonjourAccount) and self.activeAccount().server.settings_url))

        item = self.toolsMenu.itemWithTag_(43) # Buy PSTN access
        item.setEnabled_(bool(not isinstance(account, BonjourAccount) and self.activeAccount().server.settings_url))

    def updateCallMenu(self):
        menu = self.callMenu

        while menu.numberOfItems() > 6:
            menu.removeItemAtIndex_(6)

        account = self.activeAccount()

        item = menu.itemWithTag_(44) # Join Conference
        item.setEnabled_(bool(not isinstance(account, BonjourAccount) and self.backend.isMediaTypeSupported('chat')))

        if NSApp.delegate().applicationName == 'Blink Lite':
            item.setTitle_(u'Join Conference...')

        def format_account_item(account, mwi_data, mwi_format_new, mwi_format_nonew):
            a = NSMutableAttributedString.alloc().init()
            normal = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(NSFont.systemFontSize()), NSFontAttributeName)
            n = NSAttributedString.alloc().initWithString_attributes_("%s    " % account.id, normal)
            a.appendAttributedString_(n)
            if mwi_data.get('messages_waiting') and mwi_data.get('new_messages') != 0:
                text = "%d new messages" % mwi_data['new_messages']
                t = NSAttributedString.alloc().initWithString_attributes_(text, mwi_format_new)
            else:
                text = "No new messages"
                t = NSAttributedString.alloc().initWithString_attributes_(text, mwi_format_nonew)
            a.appendAttributedString_(t)
            return a

        mini_blue = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(10), NSFontAttributeName,
            NSColor.alternateSelectedControlColor(), NSForegroundColorAttributeName)
        mini_red = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(10), NSFontAttributeName,
            NSColor.redColor(), NSForegroundColorAttributeName)
       
        menu.addItem_(NSMenuItem.separatorItem())
        lastItem = menu.addItemWithTitle_action_keyEquivalent_("Voicemail", "", "")
        lastItem.setEnabled_(False)

        if any(account.message_summary.enabled for account in (account for account in AccountManager().iter_accounts() if not isinstance(account, BonjourAccount) and account.enabled)):
            for account in (account for account in AccountManager().iter_accounts() if not isinstance(account, BonjourAccount) and account.enabled and account.message_summary.enabled):
                lastItem = menu.addItemWithTitle_action_keyEquivalent_(account.id, "historyClicked:", "")
                mwi_data = MWIData.get(account.id)
                lastItem.setEnabled_(account.voicemail_uri is not None)
                lastItem.setAttributedTitle_(format_account_item(account, mwi_data or {}, mini_red, mini_blue))
                lastItem.setIndentationLevel_(1)
                lastItem.setTag_(555)
                lastItem.setTarget_(self)
                lastItem.setRepresentedObject_(account)

    def conferenceHistoryClicked_(self, sender):
        item = sender.representedObject()
        target = item["target_uri"]
        participants = item["participants"] or []
        media = item["streams"] or []

        account = self.activeAccount()
        conference = self.showJoinConferenceWindow(target=target, participants=participants, media=media, default_domain=account.id.domain)
        if conference is not None:
            self.joinConference(conference.target, conference.media_types, conference.participants)

    def updateChatMenu(self):
        while self.chatMenu.numberOfItems() > 0:
            self.chatMenu.removeItemAtIndex_(0)

        account = self.activeAccount()

        try:
            contact = self.getSelectedContacts()[0]
        except IndexError:
            pass
        else:
            # Chat menu option only for contacts without a full SIP URI
            no_contact_selected = self.contactOutline.selectedRow() == -1 and self.searchOutline.selectedRow() == -1
            item = self.chatMenu.addItemWithTitle_action_keyEquivalent_("Start Chat Session", "startChatToSelected:", "")
            item.setEnabled_((is_full_sip_uri(contact.uri) or no_contact_selected) and self.backend.isMediaTypeSupported('chat'))
            # SMS option disabled when using Bonjour Account
            item = self.chatMenu.addItemWithTitle_action_keyEquivalent_("Send SMS", "sendSMSToSelected:", "")
            item.setEnabled_(not (isinstance(account, BonjourAccount) or contact in self.model.bonjourgroup.contacts) and self.backend.isMediaTypeSupported('chat'))

    @run_in_green_thread
    @allocate_autorelease_pool
    def get_session_history_entries(self, count=10):
        def format_date(dt):
            if not dt:
                return "unknown"
            now = datetime.datetime.now()
            delta = now - dt
            if (dt.year,dt.month,dt.day) == (now.year,now.month,now.day):
                return dt.strftime("at %H:%M")
            elif delta.days <= 1:
                return "Yesterday at %s" % dt.strftime("%H:%M")
            elif delta.days < 7:
                return dt.strftime("on %A")
            elif delta.days < 300:
                return dt.strftime("on %B %d")
            else:
                return dt.strftime("on %Y-%m-%d")

        entries = {'incoming': [], 'outgoing': [], 'missed': [], 'conferences': []}

        results = SessionHistory().get_entries(direction='incoming', status= 'completed', count=count, remote_focus="0")

        for result in list(results):
            target_uri, display_name, full_uri, fancy_uri = format_identity_from_text(result.remote_uri)

            item = {
            "streams": result.media_types.split(","),
            "account": result.local_uri,
            "remote_party": fancy_uri,
            "target_uri": target_uri,
            "status": result.status,
            "failure_reason": result.failure_reason,
            "start_time": format_date(result.start_time),
            "duration": result.end_time - result.start_time,
            "focus": result.remote_focus,
            "participants": result.participants.split(",") if result.participants else []
            }
            entries['incoming'].append(item)

        results = SessionHistory().get_entries(direction='outgoing', count=count, remote_focus="0")

        for result in list(results):
            target_uri, display_name, full_uri, fancy_uri = format_identity_from_text(result.remote_uri)
            item = {
            "streams": result.media_types.split(","),
            "account": result.local_uri,
            "remote_party": fancy_uri,
            "target_uri": target_uri,
            "status": result.status,
            "failure_reason": result.failure_reason,
            "start_time": format_date(result.start_time),
            "duration": result.end_time - result.start_time,
            "focus": result.remote_focus,
            "participants": result.participants.split(",") if result.participants else []
            }
            entries['outgoing'].append(item)

        results = SessionHistory().get_entries(direction='incoming', status='missed', count=count, remote_focus="0")

        for result in list(results):
            target_uri, display_name, full_uri, fancy_uri = format_identity_from_text(result.remote_uri)
            item = {
            "streams": result.media_types.split(","),
            "account": result.local_uri,
            "remote_party": fancy_uri,
            "target_uri": target_uri,
            "status": result.status,
            "failure_reason": result.failure_reason,
            "start_time": format_date(result.start_time),
            "duration": result.end_time - result.start_time,
            "focus": result.remote_focus,
            "participants": result.participants.split(",") if result.participants else []
            }
            entries['missed'].append(item)

        results = SessionHistory().get_entries(count=count, remote_focus="1")

        for result in list(results):
            target_uri, display_name, full_uri, fancy_uri = format_identity_from_text(result.remote_uri)
            item = {
            "streams": result.media_types.split(","),
            "account": result.local_uri,
            "remote_party": fancy_uri,
            "target_uri": target_uri,
            "status": result.status,
            "failure_reason": result.failure_reason,
            "start_time": format_date(result.start_time),
            "duration": result.end_time - result.start_time,
            "focus": result.remote_focus,
            "participants":result.participants.split(",") if result.participants else []
            }
            entries['conferences'].append(item)

        self.renderHistoryMenu(entries)

    def updateHistoryMenu(self):
        self.get_session_history_entries()

    @run_in_gui_thread
    def renderHistoryMenu(self, entries):
        menu = self.historyMenu

        item = menu.itemWithTag_(100) # file transfer
        item.setEnabled_(self.backend.isMediaTypeSupported('file-transfer'))

        while menu.numberOfItems() > 4:
            menu.removeItemAtIndex_(4)
 
        mini_blue = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(10), NSFontAttributeName,
            NSColor.alternateSelectedControlColor(), NSForegroundColorAttributeName)
        mini_red = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(10), NSFontAttributeName,
            NSColor.redColor(), NSForegroundColorAttributeName)

        def format_history_menu_item(item):
            a = NSMutableAttributedString.alloc().init()
            normal = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(NSFont.systemFontSize()), NSFontAttributeName)
            n = NSAttributedString.alloc().initWithString_attributes_("%(remote_party)s  "%item, normal)
            a.appendAttributedString_(n)
            text = "%(start_time)s"%item
            if (item["duration"].seconds > 0):
                text += " for "
                dur = item["duration"]
                if dur.days > 0 or dur.seconds > 60*60:
                    text += "%i hours, "%(dur.days*60*60*24 + int(dur.seconds/(60*60)))
                s = dur.seconds%(60*60)
                text += "%02i:%02i"%(int(s/60), s%60)
            else:
                if item['status'] == 'failed':
                    text += " %s" % item['failure_reason'].capitalize()
                elif item['status'] not in ('completed', 'missed'):
                    text += " %s" % item['status'].capitalize()

            text_format = mini_red if item['status'] == 'failed' else mini_blue
            t = NSAttributedString.alloc().initWithString_attributes_(text, text_format)
            a.appendAttributedString_(t)
            return a

        lastItem = menu.addItemWithTitle_action_keyEquivalent_("Missed", "", "")
        lastItem.setEnabled_(False)
        if NSApp.delegate().applicationName == 'Blink Lite':
            lastItem = menu.addItemWithTitle_action_keyEquivalent_("Available in Blink Pro", "", "")
            lastItem.setEnabled_(False)
            lastItem.setIndentationLevel_(1)
        else:
            for item in entries['missed']:
                lastItem = menu.addItemWithTitle_action_keyEquivalent_("%(remote_party)s  %(start_time)s"%item, "historyClicked:", "")
                lastItem.setAttributedTitle_(format_history_menu_item(item))
                lastItem.setIndentationLevel_(1)
                lastItem.setTarget_(self)
                lastItem.setRepresentedObject_(item)

        menu.addItem_(NSMenuItem.separatorItem())
        lastItem = menu.addItemWithTitle_action_keyEquivalent_("Incoming", "", "")
        lastItem.setEnabled_(False)
        if NSApp.delegate().applicationName == 'Blink Lite':
            lastItem = menu.addItemWithTitle_action_keyEquivalent_("Available in Blink Pro", "", "")
            lastItem.setEnabled_(False)
            lastItem.setIndentationLevel_(1)
        else:
            for item in entries['incoming']:
                lastItem = menu.addItemWithTitle_action_keyEquivalent_("%(remote_party)s  %(start_time)s"%item, "historyClicked:", "")
                lastItem.setAttributedTitle_(format_history_menu_item(item))
                lastItem.setIndentationLevel_(1)
                lastItem.setTarget_(self)
                lastItem.setRepresentedObject_(item)

        menu.addItem_(NSMenuItem.separatorItem())
        lastItem = menu.addItemWithTitle_action_keyEquivalent_("Outgoing", "", "")
        lastItem.setEnabled_(False)
        if NSApp.delegate().applicationName == 'Blink Lite':
            lastItem = menu.addItemWithTitle_action_keyEquivalent_("Available in Blink Pro", "", "")
            lastItem.setEnabled_(False)
            lastItem.setIndentationLevel_(1)
        else:
            for item in entries['outgoing']:
                lastItem = menu.addItemWithTitle_action_keyEquivalent_("%(remote_party)s  %(start_time)s"%item, "historyClicked:", "")
                lastItem.setAttributedTitle_(format_history_menu_item(item))
                lastItem.setIndentationLevel_(1)
                lastItem.setTarget_(self)
                lastItem.setRepresentedObject_(item)

        if entries['conferences']:
            menu.addItem_(NSMenuItem.separatorItem())
            lastItem = menu.addItemWithTitle_action_keyEquivalent_("Conferences", "", "")
            lastItem.setEnabled_(False)

            if NSApp.delegate().applicationName == 'Blink Lite':
                lastItem = menu.addItemWithTitle_action_keyEquivalent_("Available in Blink Pro", "", "")
                lastItem.setEnabled_(False)
                lastItem.setIndentationLevel_(1)
            else:
                for item in entries['conferences']:
                    lastItem = menu.addItemWithTitle_action_keyEquivalent_("%(remote_party)s  %(start_time)s"%item, "conferenceHistoryClicked:", "")
                    lastItem.setAttributedTitle_(format_history_menu_item(item))
                    lastItem.setIndentationLevel_(1)
                    lastItem.setTarget_(self)
                    lastItem.setRepresentedObject_(item)

        if NSApp.delegate().applicationName != 'Blink Lite':
            menu.addItem_(NSMenuItem.separatorItem())
            lastItem = menu.addItemWithTitle_action_keyEquivalent_("Clear History", "historyClicked:", "")
            lastItem.setEnabled_(True if entries['conferences'] or entries['incoming'] or entries['outgoing'] or entries['missed'] else False)
            lastItem.setTag_(444)
            lastItem.setTarget_(self)

    @allocate_autorelease_pool
    def delete_session_history_entries(self):
        SessionHistory().delete_entries()

    def historyClicked_(self, sender):
        if sender.tag() == 444:
            self.delete_session_history_entries()
        elif sender.tag() == 555:
            # Voicemail
            account = sender.representedObject()
            BlinkLogger().log_info(u"Voicemail option pressed for account %s" % account.id)
            if account.voicemail_uri is None:
                return
            target_uri = self.backend.parse_sip_uri(account.voicemail_uri, account)
            session = SessionController.alloc().initWithAccount_target_displayName_(account, target_uri, None)
            self.sessionControllers.append(session)
            session.setOwner_(self)
            session.startAudioSession()
        else:
            item = sender.representedObject()
            target_uri = item["target_uri"]
            try:
                account = AccountManager().get_account(item["account"])
            except:
                account = None

            if account and account.enabled:
                # auto-select the account
                AccountManager().default_account = account
                self.refreshAccountList()

            self.searchBox.setStringValue_(target_uri)
            self.searchContacts()
            self.window().makeFirstResponder_(self.searchBox)
            self.window().makeKeyWindow()

    @objc.IBAction
    def redialLast_(self, sender):
        self.get_last_outgoing_session_from_history()

    @run_in_green_thread
    @allocate_autorelease_pool
    def get_last_outgoing_session_from_history(self):
        results = SessionHistory().get_entries(direction='outgoing', count=1)
        try:
            session_info = list(results)[0]
        except IndexError:
            pass
        else:
            self.redial(session_info)      

    @run_in_gui_thread
    def redial(self, session_info):
        try:
            account = AccountManager().get_account(session_info.local_uri)
        except:
            account = None

        target_uri = format_identity_from_text(session_info.remote_uri)[0]
        streams = session_info.media_types.split(",")

        BlinkLogger().log_info(u"Redial session from %s to %s, with %s" % (account, target_uri, streams))
        if not account:
            account = self.activeAccount()
        target_uri = self.backend.parse_sip_uri(target_uri, account)
        session = SessionController.alloc().initWithAccount_target_displayName_(account, target_uri, None)
        self.sessionControllers.append(session)
        session.setOwner_(self)

        if 'audio' in streams and 'chat' in streams:
            # give priority to chat stream so that we do not open audio drawer for composite streams
            sorted_streams = sorted(streams, key=lambda stream: 0 if stream=='chat' else 1)
            session.startCompositeSessionWithStreamsOfTypes(sorted_streams)
        elif 'audio' in streams:
            session.startAudioSession()
        elif 'chat' in streams:
            session.startChatSession()

    @objc.IBAction
    def sendFile_(self, sender):
        account = self.activeAccount()
        if not account:
            NSRunAlertPanel(u"Cannot Send File", u"There are currently no active SIP accounts", u"OK", None, None)
            return
        try:
            contact = self.getSelectedContacts()[0]
        except IndexError:
            pass
        else:
            if contact in self.model.bonjourgroup.contacts:
                account = BonjourAccount()
            openFileTransferSelectionDialog(account, contact.uri)

    @objc.IBAction
    def viewHistory_(self, sender):
        try:
            contact = self.getSelectedContacts()[0]
        except IndexError:
            pass
        else:
            self.showHistoryViewer_(None)
            self.historyViewer.filterByContact(contact.uri)

    def updateRecordingsMenu(self):
        def format_item(name, when):
            a = NSMutableAttributedString.alloc().init()
            normal = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(NSFont.systemFontSize()), NSFontAttributeName)
            n = NSAttributedString.alloc().initWithString_attributes_(name+"    ", normal)
            a.appendAttributedString_(n)
            mini_blue = NSDictionary.dictionaryWithObjectsAndKeys_(NSFont.systemFontOfSize_(10), NSFontAttributeName,
                NSColor.alternateSelectedControlColor(), NSForegroundColorAttributeName)
            t = NSAttributedString.alloc().initWithString_attributes_(when, mini_blue)
            a.appendAttributedString_(t)
            return a

        while not self.recordingsMenu.itemAtIndex_(0).isSeparatorItem():
            self.recordingsMenu.removeItemAtIndex_(0)
        self.recordingsMenu.itemAtIndex_(1).setRepresentedObject_(self.backend.get_audio_recordings_directory())

        recordings = self.backend.get_audio_recordings()[-10:]
        for dt, name, f in recordings:
            title = name + "  " + dt
            item = self.recordingsMenu.insertItemWithTitle_action_keyEquivalent_atIndex_(title, "recordingClicked:", "", 0)
            item.setTarget_(self)
            item.setRepresentedObject_(f)
            item.setAttributedTitle_(format_item(name,dt))
        else:
            item = self.recordingsMenu.insertItemWithTitle_action_keyEquivalent_atIndex_("No recordings available", "", "", 0)
            item.setEnabled_(False)

    @objc.IBAction
    def recordingClicked_(self, sender):
        NSWorkspace.sharedWorkspace().openFile_(sender.representedObject())

    @objc.IBAction
    def toggleDialPadClicked_(self, sender):
        self.mainTabView.selectTabViewItemWithIdentifier_("dialpad" if self.mainTabView.selectedTabViewItem().identifier() != "dialpad" else "contacts")

        frame = self.window().frame()
        old_top_left  = frame.origin.y + frame.size.height
        frame.size.width = 274

        self.window().makeKeyWindow()

        if self.mainTabView.selectedTabViewItem().identifier() == "dialpad":
            if not isinstance(self.window().firstResponder(), AudioSession):
                self.window().makeFirstResponder_(self.searchBox)

            self.searchBox.cell().setPlaceholderString_("Enter Phone Number")
            self.searchBox.setToolTip_(u'You may type digits or letters, letters will automatically be translated into digits. Press enter or click # on the dialpad to start the call')

            if not isinstance(self.window().firstResponder(), AudioSession):
                self.window().makeFirstResponder_(self.searchBox)

            new_value = ""
            for l in unicode(self.searchBox.stringValue().strip()):
                new_value = new_value + translate_alpha2digit(l)
            else:
                self.searchBox.setStringValue_(new_value)

            self.originalWindowPosition = self.window().frame()

            frame.size.height = 480
            self.window().setContentMinSize_(frame.size)
            self.window().setContentMaxSize_(frame.size)
            self.window().setContentSize_(frame.size)

        else:
            self.searchBox.cell().setPlaceholderString_("Search Contacts or Enter Address")
            self.searchBox.setToolTip_(u'You may type text to search for contacts or press enter to start a call to an arbitrary address or phone number')

            frame.size.height = 132
            self.window().setContentMinSize_(frame.size)

            frame.size.height = 2000
            frame.size.width = 800
            self.window().setContentMaxSize_(frame.size)

            if self.originalWindowPosition is not None:
                self.window().setFrame_display_animate_(self.originalWindowPosition, True, False)

            self.searchContacts()

    def playSilence(self):
        # used to keep the audio device open
        audio_active = any(sess.hasStreamOfType("audio") for sess in self.sessionControllers)
        if not audio_active and SIPApplication.voice_audio_bridge:
            if self.silence_player is None:
                self.silence_player = WavePlayer(SIPApplication.voice_audio_mixer, Resources.get('silence.wav'), volume=0, loop_count=15)
                SIPApplication.voice_audio_bridge.add(self.silence_player)

            if not self.silence_player.is_active:
                self.silence_player.start()

    @objc.IBAction
    def dialPadButtonClicked_(self, sender):
        self.playSilence()

        if sender:
            tag = sender.tag()
            if tag == 10:
               key = '*'
            elif tag == 11:
               key = '#'
            else:
               key = str(tag)

            if key in string.digits+'#*':
                first_responder = self.window().firstResponder()

                if isinstance(first_responder, AudioSession) and first_responder.delegate is not None:
                    first_responder.delegate.send_dtmf(key)
                else:
                    self.searchBox.setStringValue_(unicode(self.searchBox.stringValue())+unicode(key))
                    search_box_editor = self.window().fieldEditor_forObject_(True, self.searchBox)
                    search_box_editor.setSelectedRange_(NSMakeRange(len(self.searchBox.stringValue()), 0))
                    search_box_editor.setNeedsDisplay_(True)

                    self.addContactButtonDialPad.setEnabled_(True)
                    self.play_dtmf(key)

                    if key == '#':
                        target = unicode(self.searchBox.stringValue()).strip()[:-1]
                        if not target:
                            return

                        self.startSessionWithSIPURI(target)
                        self.resetWidgets()

                    self.updateActionButtons()

    def play_dtmf(self, key):
        self.playSilence()
        if SIPApplication.voice_audio_bridge:
            filename = 'dtmf_%s_tone.wav' % {'*': 'star', '#': 'pound'}.get(key, key)
            wave_player = WavePlayer(SIPApplication.voice_audio_mixer, Resources.get(filename), volume=50)
            SIPApplication.voice_audio_bridge.add(wave_player)
            wave_player.start()


    @objc.IBAction
    def showAccountSettings_(self, sender):
        account = self.activeAccount()
        if not self.accountSettingsPanels.has_key(account):
            self.accountSettingsPanels[account] = AccountSettings.createWithOwner_(self)
        self.accountSettingsPanels[account].showSettingsForAccount_(account)

    @objc.IBAction
    def showAccountDirectory_(self, sender):
        account = self.activeAccount()
        if not self.accountSettingsPanels.has_key(account):
            self.accountSettingsPanels[account] = AccountSettings.alloc().initWithOwner_(self)
        self.accountSettingsPanels[account].showDirectoryForAccount_(account)

    @objc.IBAction
    def showPSTNAccess_(self, sender):
        account = self.activeAccount()
        if not self.accountSettingsPanels.has_key(account):
            self.accountSettingsPanels[account] = AccountSettings.createWithOwner_(self)
        self.accountSettingsPanels[account].showPSTNAccessforAccount_(account)

    @objc.IBAction
    def showServerHistory_(self, sender):
        account = self.activeAccount()
        if not self.accountSettingsPanels.has_key(account):
            self.accountSettingsPanels[account] = AccountSettings.createWithOwner_(self)
        self.accountSettingsPanels[account].showServerHistoryForAccount_(account)

    @objc.IBAction
    def close_(self, sender):
        self.window().close()

    def updateContactContextMenu(self):
        if self.mainTabView.selectedTabViewItem().identifier() == "contacts":
            sel = self.contactOutline.selectedRow()
            if sel < 0:
                item = None
            else:
                item = self.contactOutline.itemAtRow_(sel)
        else:
            sel = self.searchOutline.selectedRow()
            if sel < 0:
                item = None
            else:
                item = self.searchOutline.itemAtRow_(sel)

        if item is None:
            for item in self.contactContextMenu.itemArray():
                item.setEnabled_(False)
            return

        while self.contactContextMenu.numberOfItems() > 0:
            self.contactContextMenu.removeItemAtIndex_(0)

        if type(item) == BlinkContact:
            has_full_sip_uri = is_full_sip_uri(item.uri)
            self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Start Audio Session", "startAudioToSelected:", "")
            chat_item = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Start Chat Session", "startChatToSelected:", "")
            chat_item.setEnabled_(has_full_sip_uri and self.backend.isMediaTypeSupported('chat'))
            video_item = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Start Video Session", "startVideoToSelected:", "")
            video_item.setEnabled_(False)
            sms_item = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Send SMS", "sendSMSToSelected:", "")
            sms_item.setEnabled_(item not in self.model.bonjourgroup.contacts and not isinstance(self.activeAccount(), BonjourAccount) and self.backend.isMediaTypeSupported('chat'))
            self.contactContextMenu.addItem_(NSMenuItem.separatorItem())
            sf_item = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Send File(s)...", "sendFile:", "")
            sf_item.setEnabled_(has_full_sip_uri and self.backend.isMediaTypeSupported('file-transfer'))
            if item not in self.model.bonjourgroup.contacts:
                self.contactContextMenu.addItem_(NSMenuItem.separatorItem())
                sf_item = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("View History...", "viewHistory:", "")
                sf_item.setEnabled_(has_full_sip_uri and NSApp.delegate().applicationName != 'Blink Lite')
            self.contactContextMenu.addItem_(NSMenuItem.separatorItem())
            contact = item.display_name
            mitem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Request Desktop from %s" % contact, "startDesktopToSelected:", "")
            mitem.setTag_(1)
            mitem.setEnabled_(has_full_sip_uri and self.backend.isMediaTypeSupported('desktop-sharing'))
            mitem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Share My Desktop with %s" % contact, "startDesktopToSelected:", "")
            mitem.setTag_(2)
            mitem.setEnabled_(has_full_sip_uri and self.backend.isMediaTypeSupported('desktop-sharing'))
            self.contactContextMenu.addItem_(NSMenuItem.separatorItem())
            if item.addressbook_id:
                lastItem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Edit in AddressBook...", "editContact:", "")
            else:
                lastItem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Edit", "editContact:", "")
                lastItem.setEnabled_(item.editable)
            lastItem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Delete", "deleteContact:", "")
            lastItem.setEnabled_(item.editable)
        else:
            lastItem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Rename", "editContact:", "")
            lastItem.setEnabled_(not item.dynamic)
            lastItem = self.contactContextMenu.addItemWithTitle_action_keyEquivalent_("Delete", "deleteGroup:", "")
            lastItem.setEnabled_(not item.dynamic)

    def menuWillOpen_(self, menu):
        def setupAudioDeviceMenu(menu, tag, devices, option_name, selector):
            settings = SIPSimpleSettings()

            for i in range(100):
                old = menu.itemWithTag_(tag*100+i)
                if old:
                    menu.removeItem_(old)
                else:
                    break

            value = getattr(settings.audio, option_name)

            index = menu.indexOfItem_(menu.itemWithTag_(tag))+1

            item = menu.insertItemWithTitle_action_keyEquivalent_atIndex_("None", selector, "", index)
            item.setRepresentedObject_("None")
            item.setTarget_(self)
            item.setTag_(tag*100)
            item.setIndentationLevel_(2)
            item.setState_(NSOnState if value in (None, "None") else NSOffState)
            index += 1

            item = menu.insertItemWithTitle_action_keyEquivalent_atIndex_("System Default", selector, "", index)
            item.setRepresentedObject_("system_default")
            item.setTarget_(self)
            item.setTag_(tag*100+1)
            item.setIndentationLevel_(2)
            item.setState_(NSOnState if value in ("default", "system_default") else NSOffState)
            index += 1

            i = 2
            for dev in devices:
                item = menu.insertItemWithTitle_action_keyEquivalent_atIndex_(dev, selector, "", index)
                item.setRepresentedObject_(dev)
                item.setTarget_(self)
                item.setTag_(tag*100+i)
                item.setIndentationLevel_(2)
                i += 1
                item.setState_(NSOnState if value == dev else NSOffState)
                index += 1

        def setupAudioInputOutputDeviceMenu(menu, tag, devices, selector):
            settings = SIPSimpleSettings()
            for i in range(100):
                old = menu.itemWithTag_(tag*100+i)
                if old:
                    menu.removeItem_(old)
                else:
                    break

            if not devices:
                menu.itemWithTag_(404).setHidden_(True)
                menu.itemWithTag_(405).setHidden_(True)
            else:
                menu.itemWithTag_(404).setHidden_(False)
                menu.itemWithTag_(405).setHidden_(False)
                index = menu.indexOfItem_(menu.itemWithTag_(tag))+1
                i = 0
                for dev in devices:
                    item = menu.insertItemWithTitle_action_keyEquivalent_atIndex_(dev, selector, "", index)
                    if settings.audio.input_device == dev and settings.audio.output_device == dev:
                        state = NSOnState
                    elif dev == u'Built-in Microphone and Output' and settings.audio.input_device == u'Built-in Microphone' and settings.audio.output_device == u'Built-in Output':
                        state = NSOnState
                    else:
                        state = NSOffState
                    item.setState_(state)
                    item.setRepresentedObject_(dev)
                    item.setTarget_(self)
                    item.setTag_(tag*100+i)
                    item.setIndentationLevel_(2)
                    i += 1
                    index += 1

        if menu == self.devicesMenu:
            in_out_devices = list(set(self.backend._app.engine.input_devices) & set(self.backend._app.engine.output_devices))
            if u'Built-in Microphone' in self.backend._app.engine.input_devices and u'Built-in Output' in self.backend._app.engine.output_devices:
                in_out_devices.append(u'Built-in Microphone and Output')
            setupAudioInputOutputDeviceMenu(menu, 404, in_out_devices, "selectInputOutputDevice:")
            setupAudioDeviceMenu(menu, 401, self.backend._app.engine.output_devices, "output_device", "selectOutputDevice:")
            setupAudioDeviceMenu(menu, 402, self.backend._app.engine.input_devices, "input_device", "selectInputDevice:")
            setupAudioDeviceMenu(menu, 403, self.backend._app.engine.output_devices, "alert_device", "selectAlertDevice:")
        elif menu == self.blinkMenu:
            self.updateBlinkMenu()
        elif menu == self.historyMenu:
            self.updateHistoryMenu()
        elif menu == self.recordingsMenu:
            self.updateRecordingsMenu()
        elif menu == self.contactContextMenu:
            self.updateContactContextMenu()
        elif menu == self.statusMenu:
            self.updateStatusMenu()
        elif menu == self.callMenu:
            self.updateCallMenu()
        elif menu == self.toolsMenu:
            self.updateToolsMenu()
        elif menu == self.chatMenu:
            self.updateChatMenu()
        elif menu == self.desktopShareMenu:
            try:
                contact = self.getSelectedContacts()[0]
            except IndexError:
                pass
            else:
                item = self.desktopShareMenu.itemWithTag_(1)
                item.setTitle_("Request Desktop from %s" % contact.display_name)
                item.setEnabled_(self.backend.isMediaTypeSupported('desktop-sharing'))
                item = self.desktopShareMenu.itemWithTag_(2)
                item.setTitle_("Share My Desktop with %s" % contact.display_name)
                item.setEnabled_(self.backend.isMediaTypeSupported('desktop-sharing'))
        elif menu == self.contactsMenu:
            item = self.contactsMenu.itemWithTag_(31) # Edit Contact
            item.setEnabled_(NSApp.keyWindow() == self.window())
            item = self.contactsMenu.itemWithTag_(32) # Delete Contact
            item.setEnabled_(NSApp.keyWindow() == self.window())
            item = self.contactsMenu.itemWithTag_(33) # Edit Group
            item.setEnabled_(NSApp.keyWindow() == self.window())
            item = self.contactsMenu.itemWithTag_(34) # Delete Group
            item.setEnabled_(NSApp.keyWindow() == self.window())

            item = self.contactsMenu.itemWithTag_(42) # Dialpad
            if NSApp.delegate().applicationName == 'Blink Pro':
                item.setEnabled_(True)
                item.setTitle_('Show Dialpad' if self.mainTabView.selectedTabViewItem().identifier() != "dialpad" else 'Hide Dialpad')
            else:
                item.setEnabled_(False)
                item.setTitle_('Show Dialpad (Available in Blink Pro)')

    def selectInputDevice_(self, sender):
        settings = SIPSimpleSettings()
        dev = sender.representedObject()
        settings.audio.input_device = unicode(dev)
        settings.save()

    def selectOutputDevice_(self, sender):
        settings = SIPSimpleSettings()
        dev = sender.representedObject()
        settings.audio.output_device = unicode(dev)
        settings.save()

    def selectInputOutputDevice_(self, sender):
        settings = SIPSimpleSettings()
        dev = sender.representedObject()
        if dev == u'Built-in Microphone and Output':
            settings.audio.output_device = unicode('Built-in Output')
            settings.audio.input_device = unicode('Built-in Microphone')
        else:
            settings.audio.output_device = unicode(dev)
            settings.audio.input_device = unicode(dev)
        settings.save()

    def selectAlertDevice_(self, sender):
        settings = SIPSimpleSettings()
        dev = sender.representedObject()
        settings.audio.alert_device = unicode(dev)
        settings.save()

    def photoClicked(self, sender):
        import PhotoPicker
        if self.picker:
            return
        self.picker = PhotoPicker.PhotoPicker()
        path, image = self.picker.runModal()
        if image and path:
            self.photoImage.setImage_(image)
            NSUserDefaults.standardUserDefaults().setValue_forKey_(path, "PhotoPath")
            NotificationCenter().post_notification("BlinkContactsHaveChanged", sender=self)
        self.picker = None
        
    def getSelectedParticipant(self):
        row = self.participantsTableView.selectedRow()
        if not self.participantsTableView.isRowSelected_(row):
            return None

        try:
            return self.participants[row]
        except IndexError:
            return None

    def participantSelectionChanged_(self, notification):
        contact = self.getSelectedParticipant()
        session = self.getSelectedAudioSession()

        if not session or contact is None:
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_ADD_CONTACT).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_REMOVE_FROM_CONFERENCE).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_MUTE).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_START_AUDIO_SESSION).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_START_CHAT_SESSION).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_START_VIDEO_SESSION).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_SEND_FILES).setEnabled_(False)
        else:
            own_uri = '%s@%s' % (session.account.id.username, session.account.id.domain)
            remote_uri = format_identity_address(session.remotePartyObject)

            hasContactMatchingURI = NSApp.delegate().windowController.hasContactMatchingURI
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_ADD_CONTACT).setEnabled_(False if (hasContactMatchingURI(contact.uri) or contact.uri == own_uri or isinstance(session.account, BonjourAccount)) else True)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_REMOVE_FROM_CONFERENCE).setEnabled_(True if self.canBeRemovedFromConference(contact.uri) else False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_START_AUDIO_SESSION).setEnabled_(True if contact.uri != own_uri and not isinstance(session.account, BonjourAccount) else False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_START_CHAT_SESSION).setEnabled_(True if contact.uri != own_uri and not isinstance(session.account, BonjourAccount) else False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_START_VIDEO_SESSION).setEnabled_(False)
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_SEND_FILES).setEnabled_(True if contact.uri != own_uri and not isinstance(session.account, BonjourAccount) else False)

    # TableView dataSource
    def numberOfRowsInTableView_(self, tableView):
        if tableView == self.participantsTableView:
            try:
                return len(self.participants)
            except:
                pass
 
        return 0

    def tableView_objectValueForTableColumn_row_(self, tableView, tableColumn, row):
        if tableView == self.participantsTableView:
            try:
                if row < len(self.participants):
                    if type(self.participants[row]) in (str, unicode):
                        return self.participants[row]
                    else:
                        return self.participants[row].name
            except:
                pass
        return None
        
    def tableView_willDisplayCell_forTableColumn_row_(self, tableView, cell, tableColumn, row):
        if tableView == self.participantsTableView:
            try:
                if row < len(self.participants):
                    if type(self.participants[row]) in (str, unicode):
                        cell.setContact_(None)
                    else:
                        cell.setContact_(self.participants[row])
            except:
                pass

    def getSelectedAudioSession(self):
        session = None
        try:
            selected_audio_view = (view for view in self.sessionListView.subviews() if view.selected is True).next()
        except StopIteration:
            pass
        else:
            session = selected_audio_view.delegate.sessionController if hasattr(selected_audio_view.delegate, 'sessionController') else None

        return session
           

    @allocate_autorelease_pool
    def updateParticipantsView(self):
        self.participants = []
        session = self.getSelectedAudioSession()
        
        if session and session.conference_info is not None:
            self.participantMenu.itemWithTag_(PARTICIPANTS_MENU_GOTO_CONFERENCE_WEBSITE).setEnabled_(True if self.canGoToConferenceWebsite() else False)

            if session.account is BonjourAccount():
                own_uri = '%s@%s' % (session.account.uri.user, session.account.uri.host)
            else:
                own_uri = '%s@%s' % (session.account.id.username, session.account.id.domain)

            path = self.iconPathForSelf()
            own_icon = NSImage.alloc().initWithContentsOfFile_(path) if path else None

            for user in session.conference_info.users:
                uri = user.entity.replace("sip:", "", 1)
                uri = uri.replace("sips:", "", 1)

                active_media = []

                chat_endpoints = [endpoint for endpoint in user if any(media.media_type == 'message' for media in endpoint)]
                if chat_endpoints:
                    active_media.append('message')

                audio_endpoints = [endpoint for endpoint in user if any(media.media_type == 'audio' for media in endpoint)]
                user_on_hold = all(endpoint.status == 'on-hold' for endpoint in audio_endpoints)
                if audio_endpoints and not user_on_hold:
                    active_media.append('audio')
                elif audio_endpoints and user_on_hold:
                    active_media.append('audio-onhold')

                contact = self.getContactMatchingURI(uri)
                if contact:
                    display_name = user.display_text.value if user.display_text is not None and user.display_text.value else contact.name
                    contact = BlinkContact(uri, name=display_name, icon=contact.icon)
                else:
                    display_name = user.display_text.value if user.display_text is not None and user.display_text.value else uri
                    contact = BlinkContact(uri, name=display_name)

                contact.setActiveMedia(active_media)

                # detail will be reset on receival of next conference-info update
                if uri in session.pending_removal_participants:
                    contact.setDetail('Removal requested...')

                if own_uri and own_icon and contact.uri == own_uri:
                    contact.setIcon(own_icon)

                if contact not in self.participants:
                    self.participants.append(contact)

            self.participants.sort(key=attrgetter('name'))

            # Add invited participants if any
            if session.invited_participants:
                for contact in session.invited_participants:
                    self.participants.append(contact)
 
        self.participantsTableView.reloadData()
        sessions_frame = self.sessionsView.frame()

        # adjust splitter
        if len(self.participants) and self.drawerSplitterPosition is None and sessions_frame.size.height > 130:
            participants_frame = self.participantsView.frame()
            participants_frame.size.height = 130
            sessions_frame.size.height -= 130
            self.drawerSplitterPosition = {'topFrame': sessions_frame, 'bottomFrame': participants_frame}

        self.resizeDrawerSplitter()
            
    @objc.IBAction
    def userClickedParticipantMenu_(self, sender):
        session = self.getSelectedAudioSession()
        if session:
            tag = sender.tag()

            row = self.participantsTableView.selectedRow()
            try:
                object = self.participants[row]
            except IndexError:
                return

            uri = object.uri
            display_name = object.display_name

            if tag == PARTICIPANTS_MENU_ADD_CONTACT:
                self.addContact(uri, display_name)
            elif tag == PARTICIPANTS_MENU_ADD_CONFERENCE_CONTACT:
                remote_uri = format_identity_address(session.remotePartyObject)
                display_name = None
                if session.conference_info is not None:
                    conf_desc = session.conference_info.conference_description
                    display_name = unicode(conf_desc.display_text)
                self.addContact(remote_uri, display_name)
            elif tag == PARTICIPANTS_MENU_REMOVE_FROM_CONFERENCE:
                ret = NSRunAlertPanel(u"Remove from conference", u"You will request the conference server to remove %s from the room. Are your sure?" % display_name, u"Remove", u"Cancel", None)
                if ret == NSAlertDefaultReturn:
                    self.removeParticipant(uri)
            elif tag == PARTICIPANTS_MENU_INVITE_TO_CONFERENCE:
                self.addParticipants()
            elif tag == PARTICIPANTS_MENU_GOTO_CONFERENCE_WEBSITE:
                NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(session.conference_info.host_info.web_page.value))
            elif tag == PARTICIPANTS_MENU_START_AUDIO_SESSION:
                self.startSessionWithAccount(session.account, uri, "audio")
            elif tag == PARTICIPANTS_MENU_START_VIDEO_SESSION:
                self.startSessionWithAccount(session.account, uri, "video")
            elif tag == PARTICIPANTS_MENU_START_CHAT_SESSION:
                self.startSessionWithAccount(session.account, uri, "chat")
            elif tag == PARTICIPANTS_MENU_SEND_FILES:
                openFileTransferSelectionDialog(session.account, uri)

    def removeParticipant(self, uri):
        session = self.getSelectedAudioSession()
        if session:
            # remove uri from invited participants
            try:
               contact = (contact for contact in session.invited_participants if contact.uri == uri).next()
            except StopIteration:
               pass
            else:
               try:
                   session.invited_participants.remove(contact)
               except ValueError:
                   pass

            if session.remote_focus and self.isConferenceParticipant(uri):
                session.log_info(u"Request server for removal of %s from conference" % uri)
                session.pending_removal_participants.add(uri)
                session.session.conference.remove_participant(uri)

            self.participantsTableView.deselectAll_(self)

    def isConferenceParticipant(self, uri):
        session = self.getSelectedAudioSession()
        if session and hasattr(session.conference_info, "users"):
            for user in session.conference_info.users:
                participant = user.entity.replace("sip:", "", 1)
                participant = participant.replace("sips:", "", 1)
                if participant == uri:
                    return True

        return False

    def isInvitedParticipant(self, uri):
        session = self.getSelectedAudioSession()
        try:
           return uri in (contact.uri for contact in session.invited_participants)
        except AttributeError:
           return False

    def canGoToConferenceWebsite(self):
        session = self.getSelectedAudioSession()
        if session.conference_info and session.conference_info.host_info and session.conference_info.host_info.web_page:
            return True
        return False

    def canBeRemovedFromConference(self, uri):
        session = self.getSelectedAudioSession()
        own_uri = '%s@%s' % (session.account.id.username, session.account.id.domain)
        return session and (self.isConferenceParticipant(uri) or self.isInvitedParticipant(uri)) and own_uri != uri

    def resizeDrawerSplitter(self):
        session = self.getSelectedAudioSession()
        if session and session.conference_info is not None and not self.collapsedState:
            if self.drawerSplitterPosition is not None:
                self.sessionsView.setFrame_(self.drawerSplitterPosition['topFrame'])
                self.participantsView.setFrame_(self.drawerSplitterPosition['bottomFrame'])
            else:
                frame = self.participantsView.frame()
                frame.size.height = 0
                self.participantsView.setFrame_(frame)
        else:
            frame = self.participantsView.frame()
            frame.size.height = 0
            self.participantsView.setFrame_(frame)

    def drawerSplitViewDidResize_(self, notification):
        if notification.userInfo() is not None:
            self.drawerSplitterPosition = {'topFrame': self.sessionsView.frame(), 'bottomFrame': self.participantsView.frame() }

    def addParticipants(self):
        session = self.getSelectedAudioSession()
        if session:
            if session.remote_focus:
                participants = self.showAddParticipantsWindow(target=self.getConferenceTitle(), default_domain=session.account.id.domain)
                if participants is not None:
                    remote_uri = format_identity_address(session.remotePartyObject)
                    # prevent loops
                    if remote_uri in participants:
                        participants.remove(remote_uri)
                    for uri in participants:
                        if uri and "@" not in uri:
                            uri='%s@%s' % (uri, session.account.id.domain)
                        contact = self.getContactMatchingURI(uri)
                        if contact:
                            contact = BlinkContact(uri, name=contact.name, icon=contact.icon)
                        else:
                            contact = BlinkContact(uri, name=uri)
                        contact.setDetail('Invitation sent...')
                        if contact not in session.invited_participants:
                            session.invited_participants.append(contact)
                            session.participants_log.add(uri)
                            session.log_info(u"Invite %s to conference" % uri)
                            session.session.conference.add_participant(uri)

    def getConferenceTitle(self):
        title = None
        session = self.getSelectedAudioSession()
        if session:
            if session.conference_info is not None:
                conf_desc = session.conference_info.conference_description
                title = u"%s <%s>" % (conf_desc.display_text, format_identity_address(session.remotePartyObject)) if conf_desc.display_text else u"%s" % session.getTitleFull()
            else:
                title = u"%s" % session.getTitleShort() if isinstance(session.account, BonjourAccount) else u"%s" % session.getTitleFull()
        return title

    # drag/drop
    def tableView_validateDrop_proposedRow_proposedDropOperation_(self, table, info, row, oper):
        session = self.getSelectedAudioSession()
        if session:
            if session.remote_focus:
                # do not allow drag if remote party is not conference focus
                pboard = info.draggingPasteboard()
                if pboard.availableTypeFromArray_(["x-blink-sip-uri"]):
                    uri = str(pboard.stringForType_("x-blink-sip-uri"))
                    if uri:
                        uri = re.sub("^(sip:|sips:)", "", str(uri))
                    try:
                        table.setDropRow_dropOperation_(self.numberOfRowsInTableView_(table), NSTableViewDropAbove)
                        
                        # do not invite remote party itself
                        remote_uri = format_identity_address(session.remotePartyObject)
                        if uri == remote_uri:
                            return NSDragOperationNone
                        # do not invite users already invited
                        for contact in session.invited_participants:
                            if uri == contact.uri:
                                return NSDragOperationNone
                        # do not invite users already present in the conference
                        if session.conference_info is not None:
                            for user in session.conference_info.users:
                                if uri == re.sub("^(sip:|sips:)", "", user.entity):
                                    return NSDragOperationNone
                    except:
                        return NSDragOperationNone
                    return NSDragOperationAll
                elif pboard.types().containsObject_(NSFilenamesPboardType):
                    return NSDragOperationAll
            elif not isinstance(session.account, BonjourAccount):
                return NSDragOperationAll

        return NSDragOperationNone

    def tableView_acceptDrop_row_dropOperation_(self, table, info, row, dropOperation):
        pboard = info.draggingPasteboard()
        session = self.getSelectedAudioSession()

        if not session:
            return False

        if pboard.availableTypeFromArray_(["x-blink-sip-uri"]):
            uri = str(pboard.stringForType_("x-blink-sip-uri"))
            if uri:
                uri = re.sub("^(sip:|sips:)", "", str(uri))
                if "@" not in uri:
                    uri = '%s@%s' % (uri, session.account.id.domain)

            if session.remote_focus:
                contact = self.getContactMatchingURI(uri)
                if contact:
                    contact = BlinkContact(uri, name=contact.name, icon=contact.icon)
                else:
                    contact = BlinkContact(uri, name=uri)
                contact.setDetail('Invitation sent...')
                session.invited_participants.append(contact)
                session.participants_log.add(uri)
                session.log_info(u"Invite %s to conference" % uri)
                session.session.conference.add_participant(uri)
            return True
