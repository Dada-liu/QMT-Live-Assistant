产品功能如下：

1. 使用python服务器调用miniQMT
2. 远程服务器发送信号给python服务器，控制下单
3. 使用图形化的界面来管理python服务器连接minQMT（填写配置、监控信号）

python服务器代码逻辑参考 `../qka` 这个项目，基于html原生创建一个项目，项目MVP如下：
MVP：
1、启动minQMT
2、启动本地服务器，连接到minQMT；用获取可用金额测试
3、在聚宽改造代码
4、监控发送到QMT的连接



