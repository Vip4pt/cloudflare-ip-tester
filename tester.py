import aiohttp
import asyncio
import socket
import ping3
import statistics
import csv
import os
from datetime import datetime

# 定义域名（替换为您的 Cloudflare 域名，需启用橙云代理）
domain = 'your-domain.com'  # 请修改为您的域名，例如 example.com

# Cloudflare 机房代码到中文名称的映射
colo_to_chinese = {
    'HKG': '香港', 'LAX': '洛杉矶', 'SIN': '新加坡', 'NRT': '东京', 'KIX': '大阪',
    'TPE': '台北', 'ICN': '首尔', 'SYD': '悉尼', 'SJC': '圣何塞', 'SEA': '西雅图',
    'FRA': '法兰克福', 'LHR': '伦敦', 'CDG': '巴黎', 'AMS': '阿姆斯特丹', 'MIA': '迈阿密',
    'ATL': '亚特兰大', 'ORD': '芝加哥', 'YYZ': '多伦多'
    # 可根据 https://www.cloudflare.com/network/ 添加更多
}

# CSV 文件路径
csv_file = 'results.csv'

# 代理检查 API 地址
checkip_urls = ["https://check.proxyip.cmliussss.net/check?proxyip={ip}"]

# 国家名称规范化映射
country_mapping = {
    '香港': '中国（香港）',
    '香港特别行政区': '中国（香港）',
    '台湾': '中国（台湾）',
    '中華民國': '中国（台湾）',
    '澳门': '中国（澳门）',
    '澳門': '中国（澳门）',
    '澳门特别行政区': '中国（澳门）'
}

async def is_cloudflare(ip, domain, session):
    """异步检测 IP 是否运行 Cloudflare 服务"""
    try:
        bind_ip(domain, 443, ip)
        async with session.get(f'https://{domain}/cdn-cgi/trace', timeout=5, ssl=False) as response:
            if response.status == 200:
                trace_data = (await response.text()).split('\n')
                for line in trace_data:
                    if line.startswith('fl=') or line.startswith('colo='):
                        return True
        async with session.get(f'https://{domain}/', timeout=5, ssl=False, allow_redirects=False) as response:
            headers = response.headers
            if 'server' in headers and 'cloudflare' in headers['server'].lower():
                return True
            if 'cf-ray' in headers:
                return True
        return False
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f'检测 {ip} 是否 Cloudflare 失败: {e}')
        return False

async def get_ip_location(ip, session):
    """异步查询 IP 的地理位置（中文），规范化中国地区表示"""
    try:
        async with session.get(f'http://ip-api.com/json/{ip}?lang=zh-CN', timeout=5) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == 'success':
                    # 规范化国家字段
                    country = data.get('country', '未知')
                    country = country_mapping.get(country, country)
                    return {
                        'country': country,
                        'region': data.get('regionName', '未知'),
                        'city': data.get('city', '未知')
                    }
                else:
                    print(f'IP {ip} 地理位置查询失败: {data.get("message", "未知错误")}')
            else:
                print(f'IP {ip} 地理位置查询失败: HTTP {response.status}')
        return {'country': '未知', 'region': '未知', 'city': '未知'}
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f'查询 {ip} 地理位置失败: {e}')
        return {'country': '未知', 'region': '未知', 'city': '未知'}
    finally:
        await asyncio.sleep(2)  # 地理位置请求间隔 2 秒

async def get_cloudflare_colo(ip, domain, session):
    """异步查询 Cloudflare 数据中心（colo）"""
    try:
        bind_ip(domain, 443, ip)
        async with session.get(f'https://{domain}/cdn-cgi/trace', timeout=5, ssl=False) as response:
            if response.status == 200:
                for line in (await response.text()).split('\n'):
                    if line.startswith('colo='):
                        colo = line.split('=')[1]
                        return f'{colo} ({colo_to_chinese.get(colo, colo)})'
        return '未知'
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f'查询 {ip} 的 colo 失败: {e}')
        return '未知'

async def test_proxy_ip(ip, session):
    """异步测试 IP 是否可用作代理"""
    for url in checkip_urls:
        try:
            async with session.get(url.format(ip=ip), timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'success': data.get('success', False),
                        'port': data.get('portRemote', -1)
                    }
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f'测试 {url} 代理失败: {e}')
            continue
    return {'success': False, 'port': -1}

# 读取 IP.txt
try:
    with open('IP.txt', 'r') as f:
        ips = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print('错误: IP.txt 文件未找到')
    exit(1)

# 自定义 DNS 解析
etc_hosts = {}
def custom_resolver(builtin_resolver):
    def wrapper(*args, **kwargs):
        try:
            return etc_hosts[args[:2]]
        except KeyError:
            return builtin_resolver(*args, **kwargs)
    return wrapper
original_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = custom_resolver(original_getaddrinfo)

def bind_ip(domain, port, ip):
    key = (domain, port)
    value = (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))
    etc_hosts[key] = [value]

async def test_latency(ip, loop, count=4):
    """测试 IP 平均延迟（毫秒）"""
    latencies = []
    for _ in range(count):
        try:
            delay = await loop.run_in_executor(None, lambda: ping3.ping(ip, timeout=2))
            if delay is not None:
                latencies.append(delay * 1000)
        except Exception as e:
            print(f'{ip} 单次 ping 失败: {e}')
    return statistics.mean(latencies) if latencies else None

def read_existing_csv():
    """读取现有 CSV，移除重复 IP"""
    existing_records = []
    if os.path.exists(csv_file):
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_records.append(row)
        except Exception as e:
            print(f'读取 {csv_file} 失败: {e}')
    return existing_records

def save_to_csv(new_records):
    """保存到 CSV，移除重复 IP"""
    existing_records = read_existing_csv()
    existing_ips = {record['IP'] for record in existing_records}
    filtered_records = [record for record in existing_records if record['IP'] not in {r['IP'] for r in new_records}]
    all_records = filtered_records + new_records
    try:
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['IP', '延迟(ms)', '国家', '地区', '城市', '机房', '代理可用', '代理端口', '时间戳']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in all_records:
                writer.writerow(record)
        print(f'已保存到 {csv_file}')
    except Exception as e:
        print(f'保存到 {csv_file} 失败: {e}')

async def test_ip(ip, session, semaphore, loop):
    """异步测试单个 IP"""
    async with semaphore:
        try:
            bind_ip(domain, 443, ip)
            async with session.get(
                f'https://{domain}/',#这里可以添加一个目录或者图片地址，例如https://{domain}/?api=http://123.com/1.png
                timeout=5, ssl=False
            ) as response:
                if response.status == 200:
                    if await is_cloudflare(ip, domain, session):
                        location = await get_ip_location(ip, session)
                        colo = await get_cloudflare_colo(ip, domain, session)
                        proxy_result = await test_proxy_ip(ip, session)
                        latency = await test_latency(ip, loop)
                        record = {
                            'IP': ip,
                            '延迟(ms)': f'{latency:.2f}' if latency is not None else '测试失败',
                            '国家': location['country'],
                            '地区': location['region'],
                            '城市': location['city'],
                            '机房': colo,
                            '代理可用': '是' if proxy_result['success'] else '否',
                            '代理端口': str(proxy_result['port']),
                            '时间戳': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        if latency is not None:
                            print(f'IP: {ip}, 状态码: 200, 地理位置: {location["country"]}, {location["region"]}, {location["city"]}, 机房: {colo}, 延迟: {latency:.2f} ms, 代理可用: {"是" if proxy_result["success"] else "否"}, 代理端口: {proxy_result["port"]}')
                        else:
                            print(f'IP: {ip}, 状态码: 200, 地理位置: {location["country"]}, {location["region"]}, {location["city"]}, 机房: {colo}, 延迟: 测试失败, 代理可用: {"是" if proxy_result["success"] else "否"}, 代理端口: {proxy_result["port"]}')
                        return record
                    else:
                        print(f'IP: {ip}, 状态码: 200, 非 Cloudflare 服务, 测试跳过')
                        return None
                else:
                    print(f'IP: {ip}, 状态码: {response.status}, 测试失败')
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f'IP: {ip}, 测试失败: {e}')
            return None
        finally:
            await asyncio.sleep(1.5)

async def main():
    """主函数，分批处理 IP"""
    if domain == 'your-domain.com':
        print('错误: 请将脚本中的 domain 变量替换为您的 Cloudflare 域名（启用橙云代理）')
        exit(1)
    good_ips = []
    semaphore = asyncio.Semaphore(2)
    timeout = aiohttp.ClientTimeout(total=10)
    batch_size = 10
    async with aiohttp.ClientSession(timeout=timeout) as session:
        loop = asyncio.get_running_loop()
        for i in range(0, len(ips), batch_size):
            batch_ips = ips[i:i + batch_size]
            tasks = [test_ip(ip, session, semaphore, loop) for ip in batch_ips]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    good_ips.append(result)
            if i + batch_size < len(ips):
                print(f'批次 {i//batch_size + 1} 完成，等待 10 秒...')
                await asyncio.sleep(10)
    if good_ips:
        sorted_ips = sorted(good_ips, key=lambda r: float(r['延迟(ms)']) if r['延迟(ms)'] != '测试失败' else float('inf'))
        print('\n可用的 IP 列表（按延迟从低到高排序）：')
        for record in sorted_ips:
            print(f'IP: {record["IP"]}, 地理位置: {record["国家"]}, {record["地区"]}, {record["城市"]}, 机房: {record["机房"]}, 延迟: {record["延迟(ms)"]}, 代理可用: {record["代理可用"]}, 代理端口: {record["代理端口"]}, 时间戳: {record["时间戳"]}')
        save_to_csv(sorted_ips)
    else:
        print('\n无可用 IP')

if __name__ == '__main__':
    asyncio.run(main())
