import datetime

import forbiddenfruit

# https://discord.com/developers/docs/reference#message-formatting-timestamp-styles
styles = {"t", "T", "d", "D", "f", "F", "R"}

def strftime(self, fmt):
    if fmt in styles:
        return f"<t:{int(self.timestamp())}:{fmt}>"
    return super(self, self.__class__).strftime(fmt)

forbiddenfruit.curse(datetime.datetime, "strftime", strftime)