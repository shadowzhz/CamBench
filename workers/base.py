import threading


class BaseWorker(threading.Thread):

    def __init__(
        self,
        event_queue
    ):

        super().__init__(
            daemon=True
        )

        self.event_queue = event_queue

        self.stop_event = threading.Event()



    def stop(self):

        self.stop_event.set()



    def stopped(self):

        return self.stop_event.is_set()
    