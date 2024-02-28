from gevent import monkey
monkey.patch_all()#monkey.patch_all()能把程序变成协作式运行，就是可以帮助程序实现异步。
from gevent.queue import Queue
import threading#多线程库
import time,requests,gevent,pygame,os,sys
import tkinter as tk#创建tk窗口
from tkinter import filedialog#tk库，用来打开资源管理器获取地址

pygame.init()#pygame初始化

extes = os.path.split(os.path.realpath(__file__))[0]#获取脚本所在目录
exte = extes.replace('\\','/')#windows下转换反斜杠，避免报错
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36'}
url_list = []#创建一个空的目录用于存放取到的url
get_list = []#用来存放输出的文本
img = pygame.image.load('./ico_ttf_img/icon.ico')#窗口ico
img1 = pygame.image.load('./ico_ttf_img/dakai.png')#打开图片
size = 800,600#设置游戏窗口大小，分别是宽度和高度
ft20 = pygame.font.Font("./ico_ttf_img/simhei.ttf", 20)#设置字体
ft15 = pygame.font.Font("./ico_ttf_img/simhei.ttf", 15)#设置字体
path_m3u8,path_key = '',''#地址暂存
screen = pygame.display.set_mode(size)#初始化显示窗口
clock = pygame.time.Clock()#游戏帧数设置
downloads = True#用来判断是否开始下载
x1,y1 = 50,200#输出文本首位坐标
jindutiao = 0#进度条进程

def analyzing():#解析m3u8文件
    global downloads,path_m3u8,path_key#声明全局变量
    text = ft15.render("准备开始分析m3u8文件...",True,(0,0,0))#字体图片化
    get_list.append(text)#添加文本
    files =  os.path.splitext(path_m3u8)[-1]#获取文件后缀
    keys = os.path.splitext(path_key)[-1]
    if files == '.m3u8' and keys == '.key':
        downloads = False
        file = open(path_m3u8,'r')#打开文件
        p=file.read().splitlines()#使用次方法提取文件时注意文件大小，避免爆内存。使用.splitlines()去除换行符
        file.close()#关闭文件
        a = 0
        photo = open('./indexs.m3u8','w')#新建一个文件（如存在则覆盖）
        for i in range(len(p)):#提取m3u8的ts文件url并建立新的本地m3u8文件供ffmpeg解密合并
            if i >= 7 and i%2 != 0:#取出ts的url
                url_list.append(p[i])
                photo.write(exte+'/ts/index'+str(a)+'.ts\n')
                a += 1
            elif i == 5:#改写key地址
                photo.write(p[i]+'\n')
            else:
                photo.write(p[i]+'\n')
        photo.close()#关闭文件
        text1 = ft15.render("分析完毕,准备开始下载...",True,(0,0,0))#字体图片化
        t1 = threading.Thread(target=download)#线程任务
        t1.start()#启动线程并继续运行下面的代码
    elif files != '.m3u8' and keys == '.key':
        text1 = ft15.render("m3u8文件错误!!!",True,(0,0,0))
        path_m3u8 = ''#地址暂存
        downloads = True
    elif files == '.m3u8' and keys != '.key':
        text1 = ft15.render("key文件错误!!!",True,(0,0,0))
        path_key = ''#地址暂存
        downloads = True
    else:
        text1 = ft15.render("key文件错误!!!m3u8文件错误!!!",True,(0,0,0))
        downloads = True
    path_m3u8,path_key = '',''#地址暂存
    get_list.append(text1)#添加文本

def tk_path(pos_xy,mouse):#获取地址
    global path_m3u8,path_key
    xy1 = (670,45)
    xy2 = (670,80)
    text1 = ft20.render("m3u8文件地址:",True,(0,0,0))#字体图片化
    screen.blit(text1,(40,50))
    screen.blit(img1,xy1)
    text2 = ft20.render("key文件地址:",True,(0,0,0))#字体图片化
    screen.blit(text2,(43,85))
    screen.blit(img1,xy2)
    pygame.draw.rect(screen,(0,0,0),(170,52,500,20),1)
    pygame.draw.rect(screen,(0,0,0),(170,87,500,20),1)
    w1,h1 = img1.get_size()
    if mouse[0] == True and pos_xy >= xy1 and pos_xy[0] <= xy1[0]+w1 and pos_xy[1] <= xy1[1]+h1:#监视鼠标左键按下动作
        root = tk.Tk()#创建tk实例化
        root.withdraw()
        path_m3u8 = filedialog.askopenfilename()#返回获取到的地址
    elif mouse[0] == True and pos_xy >= xy2 and pos_xy[0] <= xy2[0]+w1 and pos_xy[1] <= xy2[1]+h1:
        root = tk.Tk()
        root.withdraw()
        path_key = filedialog.askopenfilename()
    text2 = ft15.render(path_m3u8,True,(0,0,0))#字体图片化
    screen.blit(text2,(173,53))
    text2 = ft15.render(path_key,True,(0,0,0))#字体图片化
    screen.blit(text2,(173,88))

def download():#下载开始
    global jindutiao,downloads

    tasks_list  = []#创建空的任务列表
    start = time.time()
    work = Queue()#创建队列对象，并赋值给work。
    for url in url_list:#遍历url_list
        work.put_nowait(url)#用put_nowait()函数可以把网址都放进队列里。
    def crawler():
        global jindutiao
        while not work.empty():#当队列不是空的时候，就执行下面的程序。
            url = work.get_nowait()#用get_nowait()函数可以把队列里的网址都取出。
            res = requests.get(url,headers=headers)#用requests.get()函数抓取网址。
            if res.status_code == 200:#抓取请求的状态码。
                pic = res.content#把抓取到的文件以二进制保存下载
                p=url_list.index(url)
                photo = open('./ts/index'+str(p)+'.ts','wb')# 获取pic的二进制内容
                photo.write(pic) #关闭文件
                photo.close()
            jindutiao += 1
            text = ft15.render(url,True,(0,0,0))
            get_list.append(text)
    for x in range(50):#相当于创建了n个爬虫
        task = gevent.spawn(crawler)#用gevent.spawn()函数创建执行crawler()函数的任务。
        tasks_list.append(task)#往任务列表添加任务。
    gevent.joinall(tasks_list)#用gevent.joinall方法，执行任务列表里的所有任务，就是让爬虫开始爬取网站。
    end = time.time()
    seconds = end - start
    t_m,t_s = divmod(seconds ,60)
    t_h,t_m = divmod(t_m,60)
    r_t = "下载完成，总耗时"+str(int(t_h)).zfill(2) + "时" + str(int(t_m)).zfill(2) + "分" + str(int(t_s)).zfill(2)+"秒"
    rs = "1秒后开始合并文件"
    r_t = ft15.render(r_t,True,(0,0,0))
    get_list.append(r_t)
    rs = ft15.render(rs,True,(0,0,0))
    get_list.append(rs)
    time.sleep(1)
    
    def merge():#合并文件
        def mv():#删除ts缓存
            try:
                for files in os.walk('./ts'):
                    for i in files[2]:
                        os.remove(exte+'/ts/'+i)
                    os.remove(exte+'/indexs.m3u8')
                prpr = "缓存已删除"
                arar = ft15.render(prpr,True,(0,0,0))
                get_list.append(arar)
            except:
                pass
        try:
            file_nums = os.listdir('Z:/mp4')
            file_num = str(len(file_nums)+1)
            os.system(exte+'ffmpeg -allowed_extensions ALL -protocol_whitelist "file,http,crypto,tcp" -i master.m3u8 -c copy Z:/mp4/'+file_num+'.mp4')#使用system执行cmd命令
            prpr = "合并完成"
            arar = ft15.render(prpr,True,(0,0,0))
            get_list.append(arar)
            mv()
        except:
            prpr = "合并出现问题"
            arar = ft15.render(prpr,True,(0,0,0))
            get_list.append(arar)

    merge()#合并文件
    downloads = True

def shuxin():#刷新输出文本
    if len(get_list) >= 23:#输入框限制，多余的从首位开始删除
        get_list.pop(0)
    for i in get_list:
        ixy = get_list.index(i)*15
        screen.blit(i,(x1+2,ixy+y1+2))

pygame.display.set_icon(img)#设置ico
pygame.display.set_caption("m3u8下载器")#设置显示窗口的标题内容，是一个字符串类型
while True:
    pos_xy = pygame.mouse.get_pos()#获取鼠标位置
    mouse = pygame.mouse.get_pressed()#获取鼠标按键事件
    screen.fill((250,240,245))#背景颜色
    xy1 = 350,140
    if downloads == False:
        text1 = ft20.render("正在下载",True,(0,0,0))#字体图片化
        ajr = jindutiao/len(url_list)
        aia = ajr*100
        jjr = round(aia,1)
    else:
        text1 = ft20.render("开始下载",True,(0,0,0))#字体图片化
        jjr = 0
    w1,h1 = text1.get_size()#获取按钮大小
    text2 = ft15.render("下载进度：",True,(0,0,0))#字体图片化
    screen.blit(text2,(5,552))
    pygame.draw.rect(screen,(207,207,207),(xy1[0],xy1[1],w1,h1),0)#开始下载的边框
    pygame.draw.rect(screen,(0,0,0),(75,550,600,20),1)#进度条
    pygame.draw.rect(screen,(225,225,0),(75,550,int(jjr)*6,20),0)#进度条任务
    text3 = ft15.render(str(jjr)+"%进度",True,(0,0,0))#字体图片化
    screen.blit(text3,(680,552))
    screen.blit(text1,xy1)#开始下载按钮
    pygame.draw.rect(screen,(0,0,0),(x1,y1,600,340),1)#输出文本
    for event in pygame.event.get():
        if event.type == pygame.QUIT:#获得事件类型，并逐类响应
            sys.exit()#用于退出结束游戏并退出
        elif event.type == pygame.MOUSEBUTTONUP:
            if mouse[0] == True and pos_xy >= xy1 and pos_xy[0] <= xy1[0]+w1 and pos_xy[1] <= xy1[1]+h1 and downloads == True:
                analyzing()#开始分析文件和下载
    tk_path(pos_xy,mouse)
    t1 = threading.Thread(target=shuxin)#线程任务
    t1.start()#启动线程并继续运行下面的代码
    clock.tick(1000)
    pygame.display.update()#对显示窗口进行更新，默认窗口全部重绘