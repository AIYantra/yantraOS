class OTAUpdateError(Exception):
    pass

class OTAManager:
    def __init__(self):
        self.status = "disabled"

    def check_for_updates(self):
        return False
