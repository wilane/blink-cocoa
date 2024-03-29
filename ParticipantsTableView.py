# Copyright (C) 2010-2011 AG Projects. See LICENSE for details.
#

from AppKit import *

from application.notification import NotificationCenter
from sipsimple.util import TimestampedNotificationData


class ParticipantsTableView(NSTableView):

    def menuForEvent_(self, event):
        self.window().makeFirstResponder_(self)

        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        row = self.rowAtPoint_(point)

        if row != -1:
            self.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)
            return self.menu()

    def mouseDown_(self, event):
        NotificationCenter().post_notification("BlinkTableViewSelectionChaged", sender=self, data=TimestampedNotificationData())
        NSTableView.mouseDown_(self, event)

