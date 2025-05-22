# Cloudflare IP Tester

![Python](https://img.shields.io/badge/python-3.7%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

`cloudflare-ip-tester` 是一个异步 Python 脚本，用于测试和筛选 Cloudflare 服务的 IP 地址。它验证 IP 是否运行 Cloudflare（包括第三方网络），检测 HTTP 状态码、地理位置、数据中心（colo）、代理可用性和网络延迟，并将结果按延迟排序保存到 CSV 文件。项目使用异步 HTTP 请求（`aiohttp`）优化性能，支持中文地理位置输出。

## 功能

* ​**Cloudflare 服务检测**​：验证 IP 是否运行 Cloudflare（通过 `/cdn-cgi/trace` 和响应头）。
* ​**HTTP 状态码筛选**​：仅保留状态码为 200 的 IP，非 Cloudflare IP 跳过。
* ​**地理位置查询**​：通过 `ip-api.com` 获取中文国家、地区、城市（`lang=zh-CN`）。
* ​**数据中心识别**​：解析 `colo` 代码，映射为中文（如 `NRT (东京)`）。
* ​**代理可用性测试**​：检查 IP 是否可用作代理，获取代理端口。
* ​**延迟测试**​：使用 `ping3` 测量平均延迟（毫秒）。
* ​**结果保存**​：按延迟排序，保存到 `results.csv`（UTF-8，支持中文）。
* ​**异步优化**​：基于 `aiohttp`，提升测试效率。
* ​**速率控制**​：并发限制（2 个）、地理位置请求间隔 2 秒、每批 10 IP 间隔 10 秒。

## 适用场景

* 筛选低延迟 Cloudflare IP，优化网站访问。
* 验证 Cloudflare 服务的 IP 分布和性能。
* 研究 Cloudflare 网络的地理位置和数据中心。
* 测试 Cloudflare IP 的代理可用性。

## 安装

### 环境要求

* Python 3.7+
* 操作系统：Windows、Linux、macOS
* 网络：需访问 `ip-api.com`、Cloudflare 域名和代理测试 API

### 依赖安装

```bash
pip install aiohttp ping3
```

## 使用方法

1. ​**配置 Cloudflare 域名**​：
   
   * 打开 `test_cloudflare_ip.py`，修改 `domain` 变量：
     ```python
     domain = 'your-domain.com'  # 请修改为您的域名，例如 example.com
     ```
   * 验证域名：
     ```bash
     curl -s -k https://your-domain.com/cdn-cgi/trace
     ```
2. ​**准备 IP 列表**​：
   
   * 创建 `IP.txt` 文件，每行一个 IP 地址，例如：
     ```
     163.53.246.130
     104.16.124.96
     ```
3. ​ **（可选）配置代理测试 API**​：
   
   * 默认使用 `https://check.proxyip.cmliussss.net/check?proxyip={ip}`。
   * 若需自定义，修改 `checkip_urls`：
     ```python
     checkip_urls = ["https://your-proxy-api/check?proxyip={ip}"]
     ```
   * API 需返回 JSON，如：
     ```json
     {"success": true, "portRemote": 443}
     ```
4. ​**运行脚本**​：
   
   ```bash
   python test_cloudflare_ip.py
   ```
5. ​**查看结果**​：
   
   * ​**实时输出**​：
     ```
     IP: 163.53.246.130, 状态码: 200, 地理位置: 日本, 东京都, 东京, 机房: NRT (东京), 延迟: 30.50 ms, 代理可用: 是, 代理端口: 443
     IP: 104.16.124.96, 状态码: 200, 地理位置: 美国, 加利福尼亚, 洛杉矶, 机房: XYZ (XYZ), 延迟: 45.10 ms, 代理可用: 否, 代理端口: -1
     ```
   * ​**最终列表**​：
     ```
     可用的 IP 列表（按延迟从低到高排序）：
     IP: 163.53.246.130, 地理位置: 日本, 东京都, 东京, 机房: NRT (东京), 延迟: 30.50, 代理可用: 是, 代理端口: 443, 时间戳: 2025-05-22 13:02:34
     IP: 104.16.124.96, 地理位置: 美国, 加利福尼亚, 洛杉矶, 机房: XYZ (XYZ), 延迟: 45.10, 代理可用: 否, 代理端口: -1, 时间戳: 2025-05-22 13:02:35
     ```
   * ​**CSV 文件**​（`results.csv`，UTF-8）：
     ```
     IP,延迟(ms),国家,地区,城市,机房,代理可用,代理端口,时间戳
     163.53.246.130,30.50,日本,东京都,东京,NRT (东京),是,443,2025-05-22 13:02:34
     104.16.124.96,45.10,美国,加利福尼亚,洛杉矶,XYZ (XYZ),否,-1,2025-05-22 13:02:35
     ```

## 项目结构

```
cloudflare-ip-tester/
├── test_cloudflare_ip.py  # 主脚本
├── IP.txt                 # 输入 IP 列表（需手动创建）
├── results.csv            # 输出结果（自动生成）
└── README.md              # 项目文档
```

## 配置说明

* ​**域名**​：
  * 修改 `test_cloudflare_ip.py` 中的 `domain` 为您的 Cloudflare 域名。
  * 验证：
    ```bash
    curl -s -k https://your-domain.com/cdn-cgi/trace
    ```
* ​**IP.txt**​：
  * 每行一个 IP
  
* ​**代理测试 API**​：
  * 默认 API 可能不稳定，建议部署自定义 API。
  
* ​**速率控制**​：
  * 并发：2 个请求。
  * 地理位置请求间隔：2 秒。
  * 批次间隔：每 10 IP 等待 10 秒。
  
* ​**机房列表**​：
  * `colo_to_chinese` 映射数据中心代码到中文。
  * 更新：参考 [Cloudflare 网络](https://www.cloudflare.com/network/).

## 性能

* ​**测试速度**​：100 个 IP 约 300-500 秒（5-8 分钟），分 10 批，每批 10 IP，2 个并发。
* ​**优化**​：异步请求（`aiohttp`）比同步快 3-5 倍。
* ​**调整**​：若 `ip-api.com` 返回 HTTP 429，修改 `get_ip_location` 的 `sleep`（如 3 秒）。

## 常见问题

1. ​**错误：请替换 domain 变量**​：
   * 原因：未修改 `domain = 'your-domain.com'`。
   * 解决：编辑脚本，设置您的 Cloudflare 域名。
2. ​**地理位置显示 `未知`**​：
   * 原因：`ip-api.com` 速率限制（45 次/分钟）。
   * 解决：检查 HTTP 429 日志，增加 `sleep` 时间或降低并发。
3. ​**中文乱码**​：
   * 原因：终端或编辑器不支持 UTF-8。
   * 解决：设置 `export PYTHONIOENCODING=utf-8`。
4. ​**非 Cloudflare IP 测试失败**​：
   * 原因：IP 未运行 Cloudflare（如 `27.36.125.6`）。
   * 解决：移除非 Cloudflare IP，验证：
     ```bash
     curl -s -k https://your-domain.com/cdn-cgi/trace --resolve your-domain.com:443:<IP>
     ```
5. ​**未知 `colo` 代码**​：
   * 原因：新数据中心未在 `colo_to_chinese` 中。
   * 解决：查 [Cloudflare 网络](https://www.cloudflare.com/network/)，更新映射。

## 贡献

欢迎提交 Pull Request 或报告问题：

1. Fork 仓库。
2. 创建分支：`git checkout -b feature/your-feature`。
3. 提交更改：`git commit -m "Add your feature"`。
4. 推送：`git push origin feature/your-feature`。
5. 提交 Pull Request。



## 致谢

* [Cloudflare](https://www.cloudflare.com/)：提供 `/cdn-cgi/trace` 和网络数据。
* [IP-API.com](https://ip-api.com/)：免费地理位置查询。
* [AIOHTTP](https://docs.aiohttp.org/)：异步 HTTP 库。

## 联系

* GitHub Issues：报告问题或建议。

---

*最后更新：2025 年 5 月 22 日*
