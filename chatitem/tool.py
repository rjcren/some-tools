import threading
import socket

class Server:
    def __init__(self):
        self.__clients = []
        self.__lock = threading.Lock()
        self.__server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  #SOCK_STREAM TCP协议

    def handle_socket(self, client_socket, name):
        try:
            with self.__lock:
                self.__clients.append(client_socket)
            while True:
                data = name + ": "+ client_socket.recv(1024).decode("utf-8")
                print(data)
                for client in self.__clients:
                    if client != client_socket:
                        client.sendall(data.encode("utf-8"))
        except Exception as e:
            data = f"{name} 退出连接"
            print(data)
            for client in self.__clients:
                if client != client_socket:
                    client.sendall(data.encode("utf-8"))
        finally:
            with self.__lock:
                self.__clients.remove(client_socket)
                client_socket.close()

    def start(self, address: tuple[any, ]):
        self.__server.bind(address)
        self.__server.listen(5)
        print("-"*50, "等待连接", "-" * 50)
        while True:
            client_socket, client_add = self.__server.accept()
            name = client_socket.recv(1024).decode("utf-8")
            print(client_add, "的", name, "连接成功！")
            handle = threading.Thread(target=self.handle_socket, args=(client_socket, name))
            handle.start()

        self.__server.close()

class Client:
    def __init__(self, name: str):
        self.__name = name
        self.__client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def receive(self):
        try:
            while True:
                receive_data = self.__client_socket.recv(1024).decode("utf-8")
                print(receive_data)
        except Exception as e:
            print("聊天已中断")
        finally:
            self.__client_socket.close()

    def send(self):
        try:
            print("可以开始聊天了！")
            while True:
                send_data = input()
                self.__client_socket.send(send_data.encode("utf-8"))
                if send_data.find("bye") != -1:
                    print("聊天结束！")
                    break
        except Exception as e:
            print("聊天已中断")
        finally:
            self.__client_socket.close()

    def start(self, address: tuple[any, ]):
        self.__client_socket.connect(address)
        print("连接成功！")
        self.__client_socket.send(self.__name.encode("utf-8"))
        send_thread = threading.Thread(target=self.send)
        rece_thread = threading.Thread(target=self.receive)
        rece_thread.start()
        send_thread.start()

        send_thread.join()
