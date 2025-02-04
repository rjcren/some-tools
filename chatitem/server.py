import threading
import socket
from tkinter import *
from tkinter import messagebox  # 不写报错
import re
import logging
import time

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="server.log",
    filemode="w",
    encoding="utf-8",
)


class ServerApp:
    def __init__(self, master):
        self.__clients = {}
        self.__file_send_flags = {}
        self.__lock = threading.Lock()
        self.__server = None
        self.__start = False

        self.master = master
        self.master.title("服务器端")
        self.master.geometry(
            f"470x270+{master.winfo_screenwidth()//2-270}+{master.winfo_screenheight()//2-200}"
        )

        self.host_label = Label(self.master, text="主机号:")
        self.host_label.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.host_entry = Entry(self.master, width=15)
        self.host_entry.grid(row=0, column=1, padx=(0, 5), pady=5)
        self.port_label = Label(self.master, text="端口号:")
        self.port_label.grid(row=0, column=2, padx=10, pady=5, sticky="e")
        self.port_entry = Entry(self.master, width=7)
        self.port_entry.grid(row=0, column=3, padx=(0, 5), pady=5)

        self.start_server = Button(self.master, text="打开服务器", command=self.start)
        self.start_server.grid(row=0, column=4, padx=10, pady=5)
        self.stop_server = Button(self.master, text="关闭服务器", command=self.stop)
        self.stop_server.grid(row=0, column=5, padx=5, pady=5)
        self.stop_server.config(state=DISABLED)

        self.message_list = Listbox(self.master, width=60, height=10)
        self.message_list.grid(row=1, column=0, columnspan=7, padx=5, pady=5)
        self.message_list.insert(END, "服务器未开启")

        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def start(self):
        host = self.host_entry.get()
        port = self.port_entry.get()
        if host == "" or port == "":
            messagebox.showwarning("错误", "主机号与端口号不得为空！")
        elif (
            not re.match(r"[0-9]+.[0-9]+.[0-9]+.[0-9]+", host)
            and not host == "localhost"
        ):
            messagebox.showwarning("错误", "主机号格式错误！")
        elif not re.match(r"[0-9]+", port):
            messagebox.showwarning("错误", "端口号必须为数字")
        elif int(port) > 65535 or int(port) < 0:
            messagebox.showwarning("错误", "端口号不得大于65535或小于0！")
        else:
            try:
                self.__server = socket.socket(
                    family=socket.AF_INET, type=socket.SOCK_STREAM
                )  # SOCK_STREAM TCP协议
                self.__server.bind((host, int(port)))
                # 3.1 设置端口可重用，不然服务器关闭后几分钟之后才会关闭绑定的端口
                self.__server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.__server.listen(20)

                self.message_list.insert(END, "等待连接")
                logging.info("服务器已启动，等待连接")
                self.__start = True
                threading.Thread(target=self.listen_clients).start()
                self.start_server.config(state=DISABLED)
                self.stop_server.config(state=NORMAL)
            except OSError as e:
                self.stop(f"服务器错误，已关闭{e.strerror}")

    def listen_clients(self):
        logging.info(f"listen_clients线程已启动{self.__start}")
        temp = None
        while self.__start:
            try:
                client_socket, client_add = self.__server.accept()
                logging.info(f"申请连接用户：{client_socket}")
                if client_socket == temp:
                    continue
                temp = client_socket
                name = client_socket.recv(1024).decode("utf-8")
                flag = False
                for n in self.__clients.keys():
                    if n == name:
                        client_socket.send("重名".encode("utf-8"))
                        client_socket.close()
                        flag = True
                        break
                if flag:
                    continue
                client_socket.send("true".encode("utf-8"))
                for client in self.__clients.values():
                    client.sendall(f"{name}连接成功！".encode("utf-8"))
                with self.__lock:
                    self.__clients[name] = client_socket
                    self.__file_send_flags[name] = False
                self.message_list.insert(END, f"{client_add}的{name}连接成功！")
                self.message_list.yview(END)
                logging.info(f"{client_add}的{name}连接成功！")
                threading.Thread(target=self.handle_socket, args=(client_socket, name)).start()
            except OSError as e:
                logging.info(f"监听中{e}")
        logging.info("listen_clients线程已关闭")

    def handle_socket(self, client_socket, name):
        logging.info(f"{name}的handle_socket线程已启动")
        try:
            while self.__start:
                rec_mes = client_socket.recv(1024).decode("utf-8")
                if rec_mes.find("system@rjcren@message") != -1:
                    temp = re.match(r"need send file, filename:([*])+!!!system@rjcren@message", rec_mes)
                    if temp:
                        self.__file_send_flags[name] = True
                        threading.Thread(target=self.handle_file, args=(client_socket, name, rec_mes.group(0))).start()
                    if rec_mes == "file send stop!!!system@rjcren@message":
                        self.__file_send_flags[name] = False
                    continue
                data = name + ": " + rec_mes
                self.message_list.insert(END, data)
                self.message_list.yview(END)
                for client in self.__clients.values():
                    client.sendall(data.encode("utf-8"))
                logging.info(f"消息转发：{data.replace("\n", "\\n")}")
        except Exception as e:
            data = f"{name} 退出连接"
            logging.error(f"{name}的消息处理时发生错误: {e.strerror}")
            self.message_list.insert(END, data)
            self.message_list.yview(END)
            for client in self.__clients.values():
                if client != client_socket:
                    client.sendall(data.encode("utf-8"))
        finally:
            with self.__lock:
                del self.__clients[name]
                del self.__file_send_flags[name]
            client_socket.close()

    def handle_file(self, client_socket, name, filename):
        while True:
            with open(name+":"+filename+"_"+time.asctime,'ab') as f:
                data = client_socket.recv(1024)
                if not self.__file_send_flags[name]: break
                f.write(data)
                client_socket.send('file send success!!!system@rjcren@message'.encode())

    def stop(self, e="服务器关闭"):
        logging.error(e)
        self.__start = False
        for client in self.__clients.values():
            client.send(e.encode("utf-8"))
            client.close()
        if self.__server:
            self.__server.close()
        self.start_server.config(state=NORMAL)
        self.stop_server.config(state=DISABLED)
        self.message_list.insert(END, e)
        self.message_list.yview(END)

    def on_closing(self):
        if self.__start:
            if not messagebox.askokcancel("提示", "是否关闭服务器？"):
                return
        self.stop("服务器关闭")
        self.master.destroy()


if __name__ == "__main__":
    root = Tk()
    app = ServerApp(root)
    root.mainloop()
