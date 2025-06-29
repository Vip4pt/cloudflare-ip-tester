import aiohttp
import asyncio
import socket
import csv
import time
import json
import os
import ipaddress
import platform
import logging
from datetime import datetime
import ping3

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
domain = "hello.domain.xyz" #可以自行搭建hello world的worker设置域名开启小黄云
url = f"https://{domain}/"
check_proxy_url = "https://check.proxyip.cmliussss.net/check?proxyip={ip}" #最好自己搭建，确保公共资源不浪费
geo_api = "http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,message,country,regionName,city,isp,org,as,query"
timeout = 5  # HTTP请求超时时间（秒）
ping_timeout = 2  # Ping超时时间（秒）
ping_count = 3    # 每个IP的Ping次数
concurrency_limit = 1000  # HTTP测试并发限制,数值越小，越精准
geo_concurrency = 20    # 地理位置查询并发限制
proxy_concurrency = 20  # 代理检查并发限制

#geo-ip的查询限制为45次/分钟，以下最优设置尽量不要修改
batch_size = 9         # 每批查询的IP数量（遵守API限制）
batch_delay = 11        # 批次之间的延迟（秒）

max_cidr_size = 256     # 最大允许的CIDR范围大小（/24）

# 完全禁用 aiohttp DNS 日志（解决 macOS 警告问题）
aiohttp_logger = logging.getLogger("aiohttp.resolver")
aiohttp_logger.setLevel(logging.CRITICAL)
aiohttp_logger = logging.getLogger("aiohttp.client")
aiohttp_logger.setLevel(logging.CRITICAL)

# 加载机房代码到中文名称的映射
def load_colo_mapping():
    mapping_file = "colo_to_chinese.json"
    colo_mapping = {}
    
    if os.path.exists(mapping_file):
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                colo_mapping = json.load(f)
            logger.info(f"成功加载 {len(colo_mapping)} 个机房代码映射")
        except Exception as e:
            logger.error(f"⚠️ 加载机房映射文件失败: {str(e)}")
    else:
        logger.warning(f"⚠️ 机房映射文件 {mapping_file} 不存在，使用默认映射")
    
    return colo_mapping

# 获取机房中文名称
def get_colo_chinese(colo_code, colo_mapping):
    if not colo_code or colo_code == "N/A":
        return "未知"
    
    # 尝试直接匹配
    if colo_code in colo_mapping:
        return colo_mapping[colo_code]
    
    # 尝试去掉括号内容后匹配
    clean_code = colo_code.split(" ")[0].split("(")[0]
    if clean_code in colo_mapping:
        return colo_mapping[clean_code]
    
    # 尝试匹配括号内的内容
    if "(" in colo_code and ")" in colo_code:
        bracket_code = colo_code.split("(")[1].split(")")[0]
        if bracket_code in colo_mapping:
            return colo_mapping[bracket_code]
    
    return colo_code  # 未找到映射，返回原始代码

# 解析IP输入（支持单个IP、CIDR范围、IPv6）
def parse_ip_input(input_line):
    try:
        # 尝试解析为CIDR
        network = ipaddress.ip_network(input_line.strip(), strict=False)
        
        # 检查CIDR范围大小
        if network.num_addresses > max_cidr_size:
            logger.warning(f"⚠️ 跳过大范围CIDR: {input_line} (包含 {network.num_addresses} 个地址)")
            return []
            
        # 返回CIDR中的所有地址
        return [str(ip) for ip in network.hosts()]
    except ValueError:
        try:
            # 尝试解析为单个IP地址（支持IPv4和IPv6）
            ip = ipaddress.ip_address(input_line.strip())
            return [str(ip)]
        except ValueError:
            # 无法解析为有效IP地址
            logger.warning(f"⚠️ 无效IP地址格式: {input_line}")
            return []

# macOS 平台使用简化的解析器
class SimpleResolver(aiohttp.resolver.AbstractResolver):
    def __init__(self, ip):
        self.ip = ip
        self.is_ipv6 = ":" in ip
        
    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host == domain:
            # 根据IP类型设置正确的family
            family = socket.AF_INET6 if self.is_ipv6 else socket.AF_INET
            return [{
                'hostname': host,
                'host': self.ip,
                'port': port,
                'family': family,
                'proto': 0,
                'flags': 0
            }]
        # 其他域名使用系统解析
        return await aiohttp.resolver.DefaultResolver().resolve(host, port, family)
    
    async def close(self):
        pass

# Windows/Linux 平台使用自定义解析器
class CustomResolver(aiohttp.resolver.AbstractResolver):
    def __init__(self, ip):
        self.ip = ip
        self._system_resolver = aiohttp.resolver.AsyncResolver()
        self.is_ipv6 = ":" in ip
        
    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host == domain:
            # 根据IP类型设置正确的family
            family = socket.AF_INET6 if self.is_ipv6 else socket.AF_INET
            return [{
                'hostname': host,
                'host': self.ip,
                'port': port,
                'family': family,
                'proto': 0,
                'flags': 0
            }]
        return await self._system_resolver.resolve(host, port, family)
    
    async def close(self):
        await self._system_resolver.close()

# 测试单个IP
async def test_ip(session, ip, semaphore):
    async with semaphore:
        try:
            # 根据平台选择解析器
            if platform.system() == 'Darwin':
                resolver = SimpleResolver(ip)
            else:
                resolver = CustomResolver(ip)
            
            connector = aiohttp.TCPConnector(resolver=resolver, ssl=False)
            
            async with aiohttp.ClientSession(connector=connector) as local_session:
                async with local_session.get(
                    url, 
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    ssl=False
                ) as response:
                    text = await response.text()
                    status = response.status
                    
                    if status == 200 and "Hello World!" in text:
                        logger.info(f"✅ Success: {ip} | Status: {status} | Response: '{text[:12]}'")
                        return ip, True, status, text[:12]
                    else:
                        logger.warning(f"❌ Fail: {ip} | Status: {status}")
                        return ip, False, status, ""
                        
        except Exception as e:
            logger.error(f"⚠️ Error: {ip} | {str(e)}")
            return ip, False, 0, ""
        finally:
            await resolver.close()

# 查询IP地理位置
async def query_geo(session, ip, semaphore):
    async with semaphore:
        try:
            url = geo_api.format(ip=ip)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                data = await response.json()
                
                if data['status'] == 'success':
                    return {
                        'ip': ip,
                        'country': data.get('country', 'N/A'),
                        'region': data.get('regionName', 'N/A'),
                        'city': data.get('city', 'N/A'),
                        'isp': data.get('isp', 'N/A'),
                    }
                else:
                    return {
                        'ip': ip,
                        'country': '查询失败',
                        'region': data.get('message', 'Unknown error'),
                        'city': 'N/A',
                        'isp': 'N/A',
                    }
                    
        except Exception as e:
            return {
                'ip': ip,
                'country': '查询异常',
                'region': str(e)[:50],
                'city': 'N/A',
                'isp': 'N/A',
            }

# 检查代理信息 - 增强错误处理
async def check_proxy(session, ip, semaphore):
    async with semaphore:
        try:
            # 格式化IPv6地址（如果适用）
            formatted_ip = f"[{ip}]" if ":" in ip else ip
            proxy_url = check_proxy_url.format(ip=formatted_ip)
            
            async with session.get(proxy_url, timeout=aiohttp.ClientTimeout(total=timeout), ssl=False) as response:
                # 首先检查内容类型
                content_type = response.headers.get('Content-Type', '').lower()
                
                if 'application/json' in content_type:
                    # 是JSON响应，直接解析
                    data = await response.json()
                else:
                    # 非JSON响应，尝试解析文本
                    text = await response.text()
                    
                    # 尝试检测是否是JSON（可能Content-Type设置错误）
                    if text.strip().startswith('{'):
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError:
                            # 不是有效的JSON，记录响应片段
                            snippet = text[:100] + ('...' if len(text) > 100 else '')
                            logger.warning(f"⚠️ Proxy check: {ip} returned non-JSON response: {snippet}")
                            return {
                                'ip': ip,
                                'proxy_available': False,
                                'proxy_port': -1,
                                'colo': 'N/A',
                                'response_time': -1
                            }
                    else:
                        # 不是JSON，记录响应片段
                        snippet = text[:100] + ('...' if len(text) > 100 else '')
                        logger.warning(f"⚠️ Proxy check: {ip} returned non-JSON response: {snippet}")
                        return {
                            'ip': ip,
                            'proxy_available': False,
                            'proxy_port': -1,
                            'colo': 'N/A',
                            'response_time': -1
                        }
                
                # 处理有效JSON响应
                return {
                    'ip': ip,
                    'proxy_available': data.get('success', False),
                    'proxy_port': data.get('portRemote', -1),
                    'colo': data.get('colo', 'N/A'),
                    'response_time': data.get('responseTime', -1)
                }
                
        except aiohttp.ClientError as e:
            # 网络请求错误
            logger.error(f"⚠️ Proxy check error: {ip} | Network error: {str(e)}")
            return {
                'ip': ip,
                'proxy_available': False,
                'proxy_port': -1,
                'colo': 'N/A',
                'response_time': -1
            }
        except json.JSONDecodeError as e:
            # JSON解析错误
            logger.error(f"⚠️ Proxy check error: {ip} | JSON decode error: {str(e)}")
            return {
                'ip': ip,
                'proxy_available': False,
                'proxy_port': -1,
                'colo': 'N/A',
                'response_time': -1
            }
        except Exception as e:
            # 其他未知错误
            logger.error(f"⚠️ Proxy check error: {ip} | Unexpected error: {str(e)}")
            return {
                'ip': ip,
                'proxy_available': False,
                'proxy_port': -1,
                'colo': 'N/A',
                'response_time': -1
            }

# Ping测试延迟（支持IPv6）
def ping_ip(ip):
    try:
        delays = []
        for _ in range(ping_count):
            # 对于IPv6地址，确保使用正确的格式
            target = ip
            if ":" in ip:
                # 移除IPv6地址的方括号（如果有）
                target = ip.strip("[]")
            
            # macOS 平台优化：增加超时时间
            current_timeout = ping_timeout * 2 if platform.system() == 'Darwin' else ping_timeout
            
            delay = ping3.ping(target, timeout=current_timeout, unit='ms')
            if delay is not None:
                delays.append(delay)
        
        if delays:
            avg_delay = sum(delays) / len(delays)
            return round(avg_delay, 2)
        else:
            return float('inf')
            
    except Exception as e:
        logger.error(f"⚠️ Ping error: {ip} | {str(e)}")
        return float('inf')

# 主异步函数
async def main():
    # 加载机房映射
    colo_mapping = load_colo_mapping()
    
    # 读取IP列表（支持CIDR和IPv6）
    ip_list = []
    with open('ip.txt', 'r') as f:
        for line in f:
            if line.strip():
                parsed_ips = parse_ip_input(line)
                if parsed_ips:
                    ip_list.extend(parsed_ips)
    
    if not ip_list:
        logger.error("No valid IP addresses found in ip.txt")
        return
    
    logger.info(f"Testing {len(ip_list)} IP addresses (including CIDR expansions)...")
    start_time = time.time()
    
    # 测试IP可用性
    semaphore = asyncio.Semaphore(concurrency_limit)
    tasks = []
    async with aiohttp.ClientSession() as session:
        for ip in ip_list:
            task = asyncio.create_task(test_ip(session, ip, semaphore))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
    
    # 收集成功的IP和状态信息
    working_ips = []
    ip_info = {}
    
    for result in results:
        ip, success, status, response_text = result
        if success:
            working_ips.append(ip)
        ip_info[ip] = {
            'status': status,
            'response_text': response_text
        }
    
    # 如果没有可用IP，直接退出
    if not working_ips:
        logger.info("\nNo working IPs found.")
        return
    
    # 查询可用IP的地理位置（分批处理）
    geo_results = []
    logger.info(f"\nFound {len(working_ips)} working IPs. Querying location in batches...")
    
    # 分批处理（每批最多45个IP）
    batches = [working_ips[i:i + batch_size] for i in range(0, len(working_ips), batch_size)]
    total_batches = len(batches)
    
    geo_sem = asyncio.Semaphore(geo_concurrency)
    
    for batch_num, batch in enumerate(batches, 1):
        logger.info(f"\nProcessing location batch {batch_num}/{total_batches} ({len(batch)} IPs)")
        
        # 处理当前批次
        batch_tasks = []
        async with aiohttp.ClientSession() as session:
            for ip in batch:
                task = asyncio.create_task(query_geo(session, ip, geo_sem))
                batch_tasks.append(task)
            
            batch_results = await asyncio.gather(*batch_tasks)
            geo_results.extend(batch_results)
        
        # 如果不是最后一批，等待一段时间
        if batch_num < total_batches:
            logger.info(f"Waiting {batch_delay} seconds before next batch...")
            await asyncio.sleep(batch_delay)
    
    # 检查代理信息（分批处理）
    proxy_results = []
    logger.info(f"\nChecking proxy info for {len(working_ips)} IPs in batches...")
    
    proxy_batches = [working_ips[i:i + batch_size] for i in range(0, len(working_ips), batch_size)]
    proxy_total_batches = len(proxy_batches)
    
    proxy_sem = asyncio.Semaphore(proxy_concurrency)
    
    for batch_num, batch in enumerate(proxy_batches, 1):
        logger.info(f"\nProcessing proxy batch {batch_num}/{proxy_total_batches} ({len(batch)} IPs)")
        
        # 处理当前批次
        batch_tasks = []
        async with aiohttp.ClientSession() as session:
            for ip in batch:
                task = asyncio.create_task(check_proxy(session, ip, proxy_sem))
                batch_tasks.append(task)
            
            batch_results = await asyncio.gather(*batch_tasks)
            proxy_results.extend(batch_results)
        
        # 如果不是最后一批，等待一段时间
        if batch_num < proxy_total_batches:
            logger.info(f"Waiting {batch_delay} seconds before next batch...")
            await asyncio.sleep(batch_delay)
    
    # 合并所有信息
    combined_results = []
    for geo in geo_results:
        ip = geo['ip']
        proxy = next((p for p in proxy_results if p['ip'] == ip), None)
        info = ip_info.get(ip, {})
        
        # 获取机房中文名称
        colo_code = proxy.get('colo', 'N/A') if proxy else 'N/A'
        colo_chinese = get_colo_chinese(colo_code, colo_mapping)
        
        # 合并数据
        combined = {
            'ip': ip,
            'status': info.get('status', 0),
            'response_text': info.get('response_text', ''),
            'country': geo.get('country', 'N/A'),
            'region': geo.get('region', 'N/A'),
            'city': geo.get('city', 'N/A'),
            'isp': geo.get('isp', 'N/A'),
            'proxy_available': proxy.get('proxy_available', False) if proxy else False,
            'proxy_port': proxy.get('proxy_port', -1) if proxy else -1,
            'colo_code': colo_code,  # 原始代码
            'colo_chinese': colo_chinese,  # 中文名称
            'response_time': proxy.get('response_time', -1) if proxy else -1
        }
        
        # 添加ping延迟
        ping_delay = ping_ip(ip)
        combined['ping_delay'] = ping_delay
        
        combined_results.append(combined)
        
        # 输出详细日志
        location = f"{combined['country']}, {combined['region']}, {combined['city']}"
        logger.info(f"IP: {ip}, 状态码: {combined['status']}, 地理位置: {location}, "
              f"机房: {combined['colo_chinese']}, 延迟: {combined['ping_delay']} ms, "
              f"代理可用: {'是' if combined['proxy_available'] else '否'}, "
              f"代理端口: {combined['proxy_port']}")
    
    # 按延迟排序结果（从低到高）
    sorted_results = sorted(
        combined_results, 
        key=lambda x: x['ping_delay'] if not isinstance(x['ping_delay'], str) else float('inf')
    )
    
    # 计算耗时
    elapsed = time.time() - start_time
    
    # 输出统计信息
    logger.info("\n" + "="*50)
    logger.info("Statistics:")
    logger.info(f"Total IPs tested: {len(ip_list)}")
    logger.info(f"Working IPs found: {len(working_ips)}")
    logger.info(f"Success rate: {len(working_ips)/len(ip_list)*100:.2f}%")
    
    # 计算平均延迟（仅统计可用的）
    if sorted_results:
        valid_latencies = [x['ping_delay'] for x in sorted_results 
                      if not isinstance(x['ping_delay'], str) 
                      and x['ping_delay'] != float('inf')]
        if valid_latencies:
            avg_latency = sum(valid_latencies) / len(valid_latencies)
            logger.info(f"Average latency: {avg_latency:.2f}ms")
    
    # 统计代理可用情况
    available_proxies = [x for x in combined_results if x['proxy_available']]
    if available_proxies:
        logger.info(f"Available proxies: {len(available_proxies)}")
        avg_proxy_time = sum(x['response_time'] for x in available_proxies) / len(available_proxies)
        logger.info(f"Average proxy response time: {avg_proxy_time:.2f}ms")
    
    logger.info(f"Total time: {elapsed:.2f} seconds")
    
    # 保存结果到CSV文件（按延迟排序）
    if sorted_results:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"working_ips_{timestamp}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            fieldnames = [
                'ip', 'status', 'response_text', 'country', 'region', 'city', 'isp',
                'ping_delay', 'proxy_available', 'proxy_port', 'colo_code', 'colo_chinese', 'response_time'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in sorted_results:
                writer.writerow(row)
        
        logger.info(f"\nResults saved to {filename}")

# 运行程序
if __name__ == "__main__":
    # 设置事件循环策略（解决 Windows 上的 RuntimeError）
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # macOS 平台优化：禁用 asyncio 调试模式
    if platform.system() == 'Darwin':
        asyncio.get_event_loop().set_debug(False)
    
    asyncio.run(main())