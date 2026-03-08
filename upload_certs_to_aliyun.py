import datetime
import os
from aliyunsdkcore.client import AcsClient
from aliyunsdkcdn.request.v20180510 import SetCdnDomainSSLCertificateRequest

def get_env_var(key):
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Environment variable {key} not set")
    return value

def file_exists_and_not_empty(file_path):
    # 如果是绝对路径，直接使用；否则展开用户目录
    if os.path.isabs(file_path):
        expanded_path = file_path
    else:
        expanded_path = os.path.expanduser(file_path)
    return os.path.isfile(expanded_path) and os.path.getsize(expanded_path) > 0

def upload_certificate(client, domain_name, cert_path, key_path):
    # 如果是绝对路径，直接使用；否则展开用户目录
    if os.path.isabs(cert_path):
        expanded_cert_path = cert_path
    else:
        expanded_cert_path = os.path.expanduser(cert_path)

    if os.path.isabs(key_path):
        expanded_key_path = key_path
    else:
        expanded_key_path = os.path.expanduser(key_path)

    if not file_exists_and_not_empty(expanded_cert_path) or not file_exists_and_not_empty(expanded_key_path):
        raise FileNotFoundError(f"Certificate or key file for domain {domain_name} is missing or empty")

    with open(expanded_cert_path, 'r') as f:
        cert = f.read()

    with open(expanded_key_path, 'r') as f:
        key = f.read()

    request = SetCdnDomainSSLCertificateRequest.SetCdnDomainSSLCertificateRequest()
    # CDN加速域名
    request.set_DomainName(domain_name)
    # 证书名称
    # 精确到秒，避免同一小时内重复运行导致 CertNameAlreadyExists
    request.set_CertName(domain_name + "_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    request.set_CertType('upload')
    request.set_SSLProtocol('on')
    request.set_SSLPub(cert)
    request.set_SSLPri(key)
    request.set_CertRegion('cn-hangzhou')

    response = client.do_action_with_exception(request)
    print(str(response, encoding='utf-8'))

def main():
    try:
        access_key_id = get_env_var('ALIYUN_ACCESS_KEY_ID')
        access_key_secret = get_env_var('ALIYUN_ACCESS_KEY_SECRET')
        domains = get_env_var('DOMAINS').split(',')
        cdn_domains = get_env_var('ALIYUN_CDN_DOMAINS').split(',')

        print(f"开始处理域名: {domains}")
        print(f"CDN域名: {cdn_domains}")

        client = AcsClient(access_key_id, access_key_secret, 'cn-hangzhou')

        for domain in domains:
            domain = domain.strip()  # 去除可能的空格
            # 使用绝对路径，避免 ~ 展开问题
            cert_path = f'/home/runner/certs/{domain}/fullchain.pem'
            key_path = f'/home/runner/certs/{domain}/privkey.pem'
            related_cdn_domains = [cdn.strip() for cdn in cdn_domains if cdn.strip().endswith(domain)]

            print(f"处理域名: {domain}")
            print(f"相关CDN域名: {related_cdn_domains}")

            for cdn_domain in related_cdn_domains:
                try:
                    print(f"正在为 {cdn_domain} 上传证书...")
                    upload_certificate(client, cdn_domain, cert_path, key_path)
                    print(f"✅ {cdn_domain} 证书上传成功")
                except Exception as e:
                    print(f"❌ {cdn_domain} 证书上传失败: {str(e)}")
                    raise

        print("🎉 所有证书上传完成!")

    except Exception as e:
        print(f"❌ 程序执行失败: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()
