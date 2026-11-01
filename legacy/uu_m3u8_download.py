from gevent import monkey
monkey.patch_all()#monkey.patch_all()能把程序变成协作式运行，就是可以帮助程序实现异步。（需要放在开头）
import gevent,time,requests,os
from tqdm import tqdm#导入进度条的包
from gevent.queue import Queue
# 为躲避反爬机制，伪装成浏览器的请求头
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36'}
#res = requests.get('https://localprod.pandateacher.com/python-manuscript/crawler-html/spider-men5.0.html') 
# 检测请求是否正确响应

exte = os.path.split(os.path.realpath(__file__))[0]#获取脚本所在目录
exte = exte.replace('\\','/')#转换反斜杠，避免报错
url_list = []#创建一个空的目录用于存放取到的url

def analyzing():#解析m3u8文件
    files =  os.path.exists("./index.m3u8")#判断目标文件是否存在
    photo = open('./indexs.m3u8','w')#新建一个文件（如存在则覆盖）
    photo.close()
    if files == True:
        file = open("./index.m3u8",'r')#打开文件
        p=file.read().splitlines()#使用次方法提取文件时注意文件大小，避免爆内存。使用.splitlines()去除换行符
        file.close()#关闭文件
        a = 0
        photo = open('./indexs.m3u8','a')
        for i in range(len(p)):#提取m3u8的ts文件url并建立新的本地m3u8文件供ffmpeg解密合并
            if i >= 7 and i%2 != 0:#如果keys1为真则为22177密钥
                url_list.append(p[i])
                photo.write(exte+'/ts/index'+str(a)+'.ts\n')
                a += 1
            elif i == 5:#改写key地址
                ia = p[i]
                ia = ia[30]
                #EXT-X-KEY:METHOD=AES-128,URI="22177.text",IV=0x44bf9caf6e745e375cccb682dce9fb4a
                #ia = 'EXT-X-KEY:METHOD=AES-128,URI="key.key"'
                photo.write(p[i]+'\n')
            else:
                photo.write(p[i]+'\n')
        photo.close()#关闭文件

urls_list = []

def download():#下载开始
    print('正在开始下载，祈祷不报错')
    start = time.time()#开始下载计时
    work = Queue()#创建队列对象，并赋值给work。
    for url in url_list:
        work.put_nowait(url)#用put_nowait()函数可以把网址都放进队列里。
    def crawler():
        while not work.empty():#当队列不是空的时候，就执行下面的程序。
            url = work.get_nowait()#用get_nowait()函数可以把队列里的网址都取出。
            res = requests.get(url,headers=headers)#用requests.get()函数抓取网址。
            if res.status_code == 200:#抓取请求的状态码。
                pic = res.content#把抓取到的文件以二进制保存下载
                p=url_list.index(url)#查询网址在列表里的位置
                photo = open('./ts/index'+str(p)+'.ts','wb')
                # 获取pic的二进制内容
                photo.write(pic) 
                # 关闭文件
                photo.close()
            else:
                urls_list.append(url)
            pbar.update(1)
    tasks_list  = []#创建空的任务列表
    with tqdm(total=len(url_list)) as pbar:
        pbar.set_description('Processing:')
        for x in range(20):#相当于创建了20个爬虫
            task = gevent.spawn(crawler)#用gevent.spawn()函数创建执行crawler()函数的任务。
            tasks_list.append(task)#往任务列表添加任务。
            gevent.joinall(tasks_list)#用gevent.joinall方法，执行任务列表里的所有任务，就是让爬虫开始爬取网站。
    end = time.time()
    seconds = end - start
    t_m,t_s = divmod(seconds ,60)
    t_h,t_m = divmod(t_m,60)
    r_t = "下载完成，总耗时"+str(int(t_h)).zfill(2) + "时" + str(int(t_m)).zfill(2) + "分" + str(int(t_s)).zfill(2)+"秒"
    print(r_t)
    print('准备开始合并文件')
    time.sleep(1)

def merge():#合并文件
    print('开始合并成mp4文件')
    try:
        os.system(exte+'ffmpeg -allowed_extensions ALL -protocol_whitelist "file,http,crypto,tcp" -i master.m3u8 -c copy output.mp4')
        print('合并完成')
    except:
        print('合并出现问题！！！')
def mv():#删除ts缓存
    for root, dirs, files in os.walk('./ts'):
        for i in files:
            os.remove(exte+'/ts/'+i)
        os.remove(exte+'/index.m3u8')

#analyzing()#解析m3u8文件
#download()#下载开始
#merge()#合并文件
#mv()#删除ts缓存
