#!/usr/bin/env python
# coding=utf-8

import os#os，系统交互模块
import time#导入时间库

def getIPv6Address():#创建一个函数，用于执行接下来的代码
    exte = os.getlogin()
    output = os.popen("ipconfig").read()#获取所有地址
    lists = output.splitlines()
    file = open('C:/Users/'+exte+'/Desktop/ip.txt','w')#打开一个文件，如不存在则创建一个，会覆盖
    temps = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())#获取当前时间并以固定方式返回
    file.write(temps+'\n')#写入时间
    listx = []
    for i in lists:
        if '以太网适配器' in i:
            file.write(i+'\n')
        if 'IPv4' in i:
            ix = i.split(': ',1)
            ix = ix[1]
            if '192' == ix[0:3]:
                file.write(i+'\n')
        if 'IPv6 地址' in i:
            ix = i.split(': ',1)
            ix = ix[1]
            if 'f' != ix[0:1]:
                print(ix)
                file.write(i+'\n')
                listx.append(ix)
    if len(listx) > 0 :
        file.write('以下是获取到的ipv6地址:'+'\n')
        for i in listx:
            file.write(i+'\n')
    file.close()#关闭文件夹

if __name__ == "__main__":#设置为主程序
    print('开始')
    getIPv6Address()#执行函数
    # i = 0
    # while True:#开始无限循环
    #     getIPv6Address()#执行函数
    #     time.sleep(600)
    #     i += 1
    #     print('第'+str(i)+'次')
