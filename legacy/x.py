from gevent import monkey
monkey.patch_all()#monkey.patch_all()能把程序变成协作式运行，就是可以帮助程序实现异步。
from gevent.queue import Queue
from tqdm import tqdm#导入进度条的包
import time,requests,os,gevent

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0'}
extes = os.path.split(os.path.realpath(__file__))[0]#获取脚本所在目录
exte = extes.replace('\\','/')#windows下转换反斜杠，避免报错
url_list = []
#存放m3u8地址
url = ''
if url == '':
    url = input('获取m3u8地址:\n')
#存放m3u8文件里的ts地址一般随便获取一个就好了（视情况），如文件里的是url则不需要获取
url_ts = ''
if url_ts == '':
    url_ts = input('获取第一个ts地址:\n')

def analyzing_f1v4():#提取ts
    global url,url_ts
    urls = requests.get(url,headers=headers)#用requests.get()函数抓取网址。
    a = 1
    if urls.status_code == 200:
        p = urls.text#获取到的内容转换成txt文本
        ps_m3u8=p.split('\n')
        per = open('./index.m3u8','w')#创建一个，m3u8文件用于合并ts文件
        for i in ps_m3u8:#提取m3u8的ts文件url并建立新的本地m3u8文件供ffmpeg合并
            try:
                if i[0] != '#':#多数不是'#'开头的都是ts地址，可以用来提取ts地址
                    us = i.split('/')
                    for ue in us:#循环取出ts名称，如:seg-x-x-x.ts,各不相同
                        if '.ts' in ue:
                            uw = ue.split('.ts')
                            uq = uw[0]+'.ts'
                            uw = exte+'/ts/seg'+str(a)+'.ts'
                            a += 1
                    if 'http' in i:#分析文件里的是不是url地址
                        per.write(uw+'\n')
                        url_list.append(i)
                    else:#如果不是url地址则分析拿到的ts地址，然后拆开重组成新的ts.url地址
                        per.write(uw+'\n')
                        resc = url_ts.split('/')#地址拆开
                        ia = ''
                        for ix in resc:#拆开拿到的ts地址然后把ts名称换成文件里的名称重组
                            if '.ts' in ix:
                                iq = ix.split('.ts')
                                ia = ia+uq
                                if iq[1] != '':
                                    ia=ia+iq[1]
                            else:
                                ia = ia+ix+'/'
                        url_list.append(ia)
                else:
                    per.write(i+'\n')
            except:
                pass
        per.close()
    else:
        print('m3u8文件下载失败: '+str(urls.status_code))
analyzing_f1v4()#提取ts

work = Queue()#创建队列对象，并赋值给work。
for url in url_list:#遍历url_list
    work.put_nowait(url)#用put_nowait()函数可以把网址都放进队列里。
def crawler():
    while not work.empty():#当队列不是空的时候，就执行下面的程序。
        url = work.get_nowait()#用get_nowait()函数可以把队列里的网址都取出。
        res = requests.get(url,headers=headers)#用requests.get()函数抓取网址。
        ps = url_list.index(url)
        p  = ps+1
        if res.status_code == 200:#抓取请求的状态码。
            pic = res.content#把抓取到的文件以二进制保存下载
            photo = open('./ts/seg'+str(p)+'.ts','wb')# 获取pic的二进制内容
            photo.write(pic) #关闭文件
            photo.close()
        pbar.update(1)

tasks_list  = []#创建空的任务列表
start = time.time()#开始计时

with tqdm(total=len(url_list)) as pbar:
    pbar.set_description('下载进度条:')
    for x in range(10):#相当于创建了n个爬虫，修改数量可以更改速度，但要考虑到宽带个内存占用率
        task = gevent.spawn(crawler)#用gevent.spawn()函数创建执行crawler()函数的任务。
        tasks_list.append(task)#往任务列表添加任务。
    gevent.joinall(tasks_list)#用gevent.joinall方法，执行任务列表里的所有任务，就是让爬虫开始爬取网站。

end = time.time()#结束计时
seconds = end - start
t_m,t_s = divmod(seconds ,60)
t_h,t_m = divmod(t_m,60)
r_t = "下载完成，总耗时"+str(int(t_h)).zfill(2) + "时" + str(int(t_m)).zfill(2) + "分" + str(int(t_s)).zfill(2)+"秒"
print(r_t)

time.sleep(1)

def mv():#删除ts缓存
    file_nums = os.listdir('Z:/mp4')
    file_num = str(len(file_nums)+1)
    os.system(exte+'/ffmpeg -i index.m3u8 -c copy Z:/mp4/'+file_num+'.mp4')#合并视频文件
    for files in os.walk('./ts'):
        for i in files[2]:
            os.remove(exte+'/ts/'+i)
        os.remove(exte+'/index.m3u8')
        print("缓存已删除")
mv()
