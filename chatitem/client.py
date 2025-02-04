from tkinter import *
from tkinter import messagebox
from tkinter import filedialog
import re
import threading
import socket
import keyboard

class ClientApp:
    def __init__(self, master):
        self.__start = False
        self.__client_socket = None

        self.master = master
        self.master.title("客户端")
        self.master.geometry(f"450x390+{master.winfo_screenwidth()//2-270}+{master.winfo_screenheight()//2-200}")

        self.host_label = Label(self.master, text="主机号:")
        self.host_label.grid(row=0, column=0, padx=(10,0), pady=5, sticky="e")
        self.host_entry = Entry(self.master, width=15)
        self.host_entry.grid(row=0, column=1, padx=(5,20), pady=5)
        self.port_label = Label(self.master, text="端口号:")
        self.port_label.grid(row=0, column=2, pady=5, sticky="e")
        self.port_entry = Entry(self.master, width=10)
        self.port_entry.grid(row=0, column=3, padx=(5,20), pady=5)
        self.name_label = Label(self.master, text="名称:")
        self.name_label.grid(row=0, column=4, pady=5, sticky="e")
        self.name_entry = Entry(self.master, width=8)
        self.name_entry.grid(row=0, column=5, pady=5)

        self.link_server = Button(self.master, text="连接服务器", width=15, height=2, command=self.start)
        self.link_server.grid(row=1, column=0, columnspan=3, padx=5, pady=10)
        self.stop_link = Button(self.master, text="断开服务器", width=15, height=2, command=self.stop)
        self.stop_link.grid(row=1, column=3, columnspan=3, padx=10, pady=10)
        self.stop_link.config(state=DISABLED)

        self.message_list = Listbox(self.master, width=60, height=10)
        self.message_list.grid(row=2, column=0, columnspan=6, pady=5, padx=(10, 0))
        self.message_list.insert(END, "请先连接服务器")

        self.send_list = Text(self.master, width=45, height=3)
        self.send_list.grid(row=3, column=0, columnspan=4, padx=(10,0), pady=5)
        self.send_message = Button(self.master, text="发送", command=self.send)
        self.send_message.grid(row=3, column=4, padx=(10, 0), pady=5)
        self.send_message.config(state=DISABLED)

        self.other = Button(self.master, text="其他", command=self.other_function)
        self.other.grid(row=3, column=5, padx=0, pady=5)
        self.other.config(state=DISABLED)

        self.__filename = StringVar()
        self.__is_send_file = False

        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def start(self):
        host = self.host_entry.get()
        port = self.port_entry.get()
        name = self.name_entry.get()
        if host == "" or port == "":
            messagebox.showwarning("错误", "主机号与端口号不得为空！")
        elif not re.match(r"[0-9]+.[0-9]+.[0-9]+.[0-9]+", host) and not host == "localhost":
            messagebox.showwarning("错误", "主机号格式错误！")
        elif not re.match(r"[0-9]+", port):
            messagebox.showwarning("错误", "端口号必须为数字")
        elif int(port) > 65535 or int(port) < 0:
            messagebox.showwarning("错误", "端口号不得大于65535或小于0！")
        elif name == "":
            messagebox.showwarning("错误", "请输入名称")
        else:
            self.__start = True
            threading.Thread(target=self.connect_server, args=(host, port, name), daemon=True).start()

    def connect_server(self, host, port, name):
        while self.__start:
            try:
                self.__client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.message_list.insert(END, "正在连接，请稍等！")
                self.stop_link.config(state=NORMAL)
                self.link_server.config(state=DISABLED)
                self.__client_socket.connect((host, int(port)))
                self.__client_socket.send(name.encode("utf-8"))
                flag = self.__client_socket.recv(1024).decode("utf-8")
                if flag == "重名":
                    self.stop("名字重复，更改名字后重新连接！")
                elif flag == "true":
                    self.message_list.insert(END, "连接成功！可以开始聊天了！")
                    self.message_list.yview(END)
                    threading.Thread(target=self.receive, daemon=True).start()
                    keyboard.add_hotkey("shift+enter", self.send)
                    self.link_server.config(state=DISABLED)
                    self.stop_link.config(state=NORMAL)
                    self.send_message.config(state=NORMAL)
                    self.other.config(state=NORMAL)
                else :
                    self.stop("连接失败，服务器未响应！")
                break
            except socket.timeout:
                self.stop(f"连接超时，请检查服务器是否正常运行")
            except OSError as e:
                self.stop(f"连接失败,{e.strerror}")

    def receive(self):
        def receive_loop():
            try:
                while self.__start:
                    receive_data = self.__client_socket.recv(1024).decode("utf-8")
                    if receive_data.find("system@rjcren@message") != -1:
                        if receive_data == "file send success!!!system@rjcren@message":
                            self.__is_send_file = False
                        continue
                    self.message_list.insert(END, receive_data)
                    self.message_list.yview(END)
            except OSError as e:
                self.stop(f"聊天已中断{e.strerror}")
            finally:
                if self.__client_socket:
                    self.__client_socket.close()
        if self.__start:
            receive_loop()

    def send(self):
        try:
            send_data = self.send_list.get("0.0", END)
            if send_data == "":
                messagebox.showwarning("错误", "输入不能为空！")
            else:
                self.__client_socket.send(send_data.encode("utf-8"))
                self.send_list.delete("0.0", END)
        except OSError as e:
            self.stop(f"聊天已中断{e.strerror}")

    def stop(self, e = "连接已关闭"):
        self.__start = False
        if self.__client_socket:
            self.__client_socket.close()
        self.message_list.insert(END, e)
        self.message_list.yview(END)
        try:
            keyboard.remove_hotkey("shift+enter")
        except KeyError:
            pass
        self.link_server.config(state=NORMAL)
        self.stop_link.config(state=DISABLED)
        self.send_message.config(state=DISABLED)
        self.other.config(state=DISABLED)

    def on_closing(self):
        if self.__start:
            if not messagebox.askokcancel("提示", "是否关闭连接？"):
                return
        self.stop()
        self.master.destroy()

    def other_function(self):
        self.other.config(state=DISABLED)
        other = Toplevel(self.master, width=120, height=50)
        other.title("其他功能")
        Button(other, text="发送文件", command=self.send_file).pack()
        other.protocol("WM_DELETE_WINDOW", self.other.config(state=NORMAL))

    def openFile(self):
        filepath = filedialog.askopenfilename()
        if filepath.strip() != "":
            self.__filename.set(filepath.strip())
        else:
            self.__filename.set("do not choose file")

    def send_file_to(self):
        def send():
            with open(self.__filename.get(),'rb') as f:
                for i in f:
                    self.__client_socket.send(i)
                    if not self.__is_send_file:
                        break
            self.__client_socket.send('file send stop!!!system@rjcren@message'.encode())

            if self.__filename.get() == "do not choose file" or self.__filename.get() == "":
                messagebox.showerror("错误", "未选取文件或选取文件无效")
                return
        self.__is_send_file = True
        self.__client_socket.send(f"need send file, filename:{self.__filename.get()}!!!system@rjcren@message".encode("utf-8"))
        threading.Thread(target=send).start()
        self.__is_send_file = False

    def send_file(self):
        file_choose = Toplevel(self.master)
        file_choose.title("选择文件")
        Entry(file_choose, textvariable=self.__filename).grid(row=1, column=1, padx=5, pady=5)
        Button(file_choose, text="选择文件", command=self.openFile).grid(row=1, column=2, padx=5, pady=5)
        Button(file_choose, text="发送",  command=self.send_file_to).grid(row=1, column=3, padx=5, pady=5)
        file_choose.mainloop()



if __name__ == "__main__":
    root = Tk()
    app = ClientApp(root)
    root.mainloop()