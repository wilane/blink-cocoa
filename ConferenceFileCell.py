# Copyright (C) 2011 AG Projects. See LICENSE for details.
#

from Foundation import *
from AppKit import *


class ConferenceFileCell(NSTextFieldCell):
    conference_file = None

    nameAttrs = NSDictionary.dictionaryWithObjectsAndKeys_(
      NSFont.systemFontOfSize_(12.0), NSFontAttributeName)

    infoAttrs = NSDictionary.dictionaryWithObjectsAndKeys_(
      NSFont.systemFontOfSize_(NSFont.labelFontSize()-1), NSFontAttributeName,
      NSColor.grayColor(), NSForegroundColorAttributeName)

    defaultIcon = None

    def drawingRectForBounds_(self, rect):
        return rect

    def cellSize(self):
        if self.conference_file is None:
            return super(ConferenceFileCell, self).cellSize()
        return NSMakeSize(100, 30)

    def drawWithFrame_inView_(self, frame, view):
        if self.conference_file is None:
            tmp = frame
            return super(ConferenceFileCell, self).drawWithFrame_inView_(tmp, view)

        if self.defaultIcon is None:
            self.defaultIcon = NSImage.imageNamed_("NSMultipleDocuments")

        icon = self.conference_file.icon or self.defaultIcon
        if icon:
            self.drawIcon(icon, 2, frame.origin.y+3, 28, 28)

        # 1st line: file name
        frame.origin.x = 35
        frame.origin.y += 2
        self.conference_file.name.drawAtPoint_withAttributes_(frame.origin, self.nameAttrs)

        # 2nd line: file sender
        point = frame.origin
        point.y += 15
        self.conference_file.sender.drawAtPoint_withAttributes_(point, self.infoAttrs)

    def drawIcon(self, icon, origin_x, origin_y, size_x, size_y):
        size = icon.size()
        rect = NSMakeRect(0, 0, size.width, size.height)
        trect = NSMakeRect(origin_x, origin_y, (size_y/size.height) * size.width, size_x)
        if icon.respondsToSelector_("drawInRect:fromRect:operation:fraction:respectFlipped:hints:"):
            # New API in Snow Leopard to correctly draw an icon in context respecting its flipped attribute
            icon.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(trect, rect, NSCompositeSourceOver, 1.0, True, None)
        else:
            # Leopard, see http://developer.apple.com/mac/library/releasenotes/cocoa/AppKit.html
            icon_flipped = icon.copy()
            icon_flipped.setFlipped_(True)
            icon_flipped.drawInRect_fromRect_operation_fraction_(trect, rect, NSCompositeSourceOver, 1.0)