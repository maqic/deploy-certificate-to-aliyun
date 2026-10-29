# deploy-certificate-to-aliyun
每两个月自动部署泛解析证书到阿里云CDN上


## 如何使用

fork该项目，并填写对应参数，再push一次代码即可（随便改点啥，workflow需要push才能触发）

 GitHub 仓库的 "Settings" -> "Secrets and variables" -> "Actions" 中添加以下 secrets：

- `ALIYUN_ACCESS_KEY_ID`：阿里云账户AK
- `ALIYUN_ACCESS_KEY_SECRET`：阿里云账户SK
- `DOMAINS`: 要设置域名的二级域名，例如要设置*.example.com，这里填写的就是example.com, 多个域名用英文逗号隔开
- `ALIYUN_CDN_DOMAINS`：设置阿里云cdn域名，一般是三级域名，例如cdn.example.com，需要跟上面的DOMAINS对应，否则会设置错误
- `EMAIL`:  证书过期时提醒的邮件

**工作流结果邮件通知**：无论成功或失败都会向 `maqic51@gmail.com` 发送邮件，需在 Secrets 中增加：
- `MAIL_USERNAME`：发件邮箱（如用 Gmail 则填 `xxx@gmail.com`）
- `MAIL_PASSWORD`：该邮箱的 SMTP 密码（Gmail 需在账号里开启「两步验证」后生成 [应用专用密码](https://myaccount.google.com/apppasswords)）

邮件包含任务状态、各 CDN 域名的公网 HTTPS 状态、线上证书到期日、剩余天数，以及线上证书是否已同步为本次新证书。邮件失败会令工作流标记失败，避免静默遗漏通知。


## 相关文档

> 这里使用的是阿里云提供的api进行的调用
>
> - 设置CDN证书：https://next.api.aliyun.com/document/Cdn/2018-05-10/SetCdnDomainSSLCertificate

---
最后更新: 2026-10-25 07:12:36

## 官网 CDN 证书

官网 dodo.saibao.fun 自 2026-10-30 接入 CDN，续期上传及报告目标在现有 ALIYUN_CDN_DOMAINS secret 基础上追加该域名，不替换或缩减原目标列表。当前使用同一 *.saibao.fun 证书；新增域名的初次部署与 HTTPS 验收由官网迁移回执记录。
