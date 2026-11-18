"""用QTest输出事件连接GPIO输入，不向固件预填期待结果。"""
import socket
import threading
import time


class GPIOWire:
    def __init__(self,connection,device='/machine/unattached/device[9]',output=0,input_pin=1):
        self.connection=connection;self.device=device;self.output=output;self.input=input_pin
        self.records=[];self.error=None;self.stop=threading.Event();self.thread=None

    def start(self):
        self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.connection.settimeout(.2)
        self.connection.sendall(f'irq_intercept_out {self.device}\nset_irq_in {self.device} unnamed-gpio-in {self.input} 0\n'.encode())
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start();return self

    def run(self):
        buffer=b''
        try:
            while not self.stop.is_set():
                try:data=self.connection.recv(4096)
                except socket.timeout:continue
                if not data:break
                if hasattr(socket,'TCP_QUICKACK'):self.connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_QUICKACK,1)
                buffer+=data
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1);self.records.append({'time':time.monotonic(),'rx':line.decode(errors='replace')})
                    fields=line.split()
                    if len(fields)==3 and fields[0]==b'IRQ' and int(fields[2])==self.output:
                        level=1 if fields[1]==b'raise' else 0
                        command=f'set_irq_in {self.device} unnamed-gpio-in {self.input} {level}\n'
                        self.connection.sendall(command.encode());self.records.append({'time':time.monotonic(),'tx':command.strip(),'observed_output_level':level})
                    elif line.startswith(b'FAIL'):raise RuntimeError(line.decode())
        except Exception as error:self.error=repr(error)

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
        self.connection.close()
