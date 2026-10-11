import os
import re
import sys
import time

import requests


# 网络请求设置
REQUEST_TIMEOUT = (10, 20)  # (连接超时, 读取超时)
MAX_ATTEMPTS = 3
RETRY_DELAYS = (10, 30)  # 第1次失败等10秒，第2次失败等30秒


# 替代 notify 功能
def send(title, message):
    print(f"{title}: {message}")


# 获取环境变量
def get_env():
    """
    获取 COOKIE_QUARK。
    多账号可使用换行或 && 分隔。
    """
    cookie_value = os.environ.get("COOKIE_QUARK")

    if not cookie_value:
        print("❌ 未添加 COOKIE_QUARK 变量，或变量为空")
        send("夸克自动签到", "❌ 未添加 COOKIE_QUARK 变量")
        sys.exit(1)

    cookie_list = re.split(r"\r?\n|&&", cookie_value)
    cookie_list = [cookie.strip() for cookie in cookie_list if cookie.strip()]

    if not cookie_list:
        print("❌ COOKIE_QUARK 中没有有效账号")
        sys.exit(1)

    return cookie_list


class Quark:
    """
    Quark 类封装签到、领取签到奖励的方法
    """

    def __init__(self, user_data):
        """
        初始化方法

        :param user_data: 用户信息，用于后续请求
        """
        self.param = user_data

    def convert_bytes(self, b):
        """
        将字节转换为 B / KB / MB / GB / TB 等
        """
        units = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")

        try:
            b = float(b)
        except (TypeError, ValueError):
            return str(b)

        i = 0

        while b >= 1024 and i < len(units) - 1:
            b /= 1024
            i += 1

        return f"{b:.2f} {units[i]}"

    def get_growth_info(self):
        """
        获取用户当前签到信息
        """
        url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/info"

        querystring = {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode"),
        }

        response = requests.get(
            url=url,
            params=querystring,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("data"):
            return data["data"]

        message = (
            data.get("message")
            or data.get("msg")
            or "获取成长信息失败"
        )

        raise RuntimeError(f"❌ 获取成长信息失败: {message}")

    def get_growth_sign(self):
        """
        执行每日签到
        """
        url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/sign"

        querystring = {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode"),
        }

        data = {
            "sign_cyclic": True
        }

        response = requests.post(
            url=url,
            json=data,
            params=querystring,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        if result.get("data"):
            return (
                True,
                result["data"].get("sign_daily_reward", 0),
            )

        message = (
            result.get("message")
            or result.get("msg")
            or "未知错误"
        )

        return False, message

    def queryBalance(self):
        """
        查询抽奖余额
        """
        url = "https://coral2.quark.cn/currency/v1/queryBalance"

        querystring = {
            "moduleCode": "1f3563d38896438db994f118d4ff53cb",
            "kps": self.param.get("kps"),
        }

        response = requests.get(
            url=url,
            params=querystring,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("data"):
            return data["data"]["balance"]

        return data.get("msg", "查询失败")

    def do_sign(self):
        """
        执行签到任务

        :return: 签到结果字符串
        """
        log = ""

        growth_info = self.get_growth_info()

        log += (
            f" {'88VIP' if growth_info.get('88VIP') else '普通用户'} "
            f"{self.param.get('user', '')}\n"
            f"💾 网盘总容量："
            f"{self.convert_bytes(growth_info.get('total_capacity', 0))}，"
            f"签到累计容量："
        )

        cap_composition = growth_info.get("cap_composition", {})

        if "sign_reward" in cap_composition:
            log += (
                f"{self.convert_bytes(cap_composition['sign_reward'])}\n"
            )
        else:
            log += "0 MB\n"

        cap_sign = growth_info.get("cap_sign")

        if not isinstance(cap_sign, dict):
            raise RuntimeError("❌ 成长信息中缺少 cap_sign 字段")

        # 今天已经签到
        if cap_sign.get("sign_daily"):
            log += (
                "✅ 签到日志: 今日已签到+"
                f"{self.convert_bytes(cap_sign.get('sign_daily_reward', 0))}，"
                f"连签进度("
                f"{cap_sign.get('sign_progress', '?')}/"
                f"{cap_sign.get('sign_target', '?')})\n"
            )

        # 今天尚未签到
        else:
            sign, sign_return = self.get_growth_sign()

            if sign:
                progress = cap_sign.get("sign_progress", 0)

                if isinstance(progress, int):
                    progress += 1
                else:
                    progress = "?"

                log += (
                    "✅ 执行签到: 今日签到+"
                    f"{self.convert_bytes(sign_return)}，"
                    f"连签进度("
                    f"{progress}/"
                    f"{cap_sign.get('sign_target', '?')})\n"
                )

            else:
                # 这里必须抛出异常。
                # 否则 Python 会返回 0，GitHub Actions 会错误地认为签到成功，
                # 随后生成当天成功缓存。
                raise RuntimeError(
                    f"❌ 签到异常: {sign_return}"
                )

        return log


def parse_user_data(cookie, index):
    """
    将 COOKIE_QUARK 中的一条账号信息解析成字典。
    """
    user_data = {}

    for item in cookie.replace(" ", "").split(";"):
        if not item:
            continue

        if "=" not in item:
            raise ValueError(
                f"第 {index} 个账号 COOKIE 格式异常: {item}"
            )

        key, value = item.split("=", 1)
        user_data[key] = value

    required = ("kps", "sign", "vcode")

    missing = [
        key
        for key in required
        if not user_data.get(key)
    ]

    if missing:
        raise ValueError(
            f"第 {index} 个账号缺少参数: {', '.join(missing)}"
        )

    return user_data


def sign_with_retry(user_data, account_index):
    """
    执行完整签到流程。

    网络连接错误、连接重置或超时时重新执行整个签到流程，
    而不是单独重放 POST。

    这样即使前一次 POST 已经在服务器端签到成功、
    但返回数据时连接断开，下一次也会先查询签到状态，
    从而识别为“今日已签到”。
    """
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if attempt > 1:
                print(
                    f"🔄 第 {account_index} 个账号开始第 "
                    f"{attempt}/{MAX_ATTEMPTS} 次尝试..."
                )

            result = Quark(user_data).do_sign()

            if attempt > 1:
                print("✅ 重试成功")

            return result

        except requests.RequestException as err:
            last_error = err

            print(
                f"⚠️ 第 {account_index} 个账号第 "
                f"{attempt}/{MAX_ATTEMPTS} 次网络请求失败"
            )

            print(
                f"错误类型: {type(err).__name__}"
            )

            print(
                f"错误信息: {err}"
            )

            if attempt < MAX_ATTEMPTS:
                delay = RETRY_DELAYS[attempt - 1]

                print(
                    f"⏳ {delay} 秒后重新尝试完整签到流程..."
                )

                time.sleep(delay)

    raise RuntimeError(
        f"❌ 连续 {MAX_ATTEMPTS} 次网络请求失败"
    ) from last_error


def main():
    """
    主函数
    """
    msg = ""

    cookie_quark = get_env()

    print(
        f"✅ 检测到共 {len(cookie_quark)} 个夸克账号\n"
    )

    for index, cookie in enumerate(cookie_quark, start=1):
        user_data = parse_user_data(cookie, index)

        msg += f"🙍🏻‍♂️ 第{index}个账号"

        # 登录 + 查询状态 + 签到
        log = sign_with_retry(
            user_data,
            index,
        )

        msg += log + "\n"

    try:
        send(
            "夸克自动签到",
            msg,
        )

    except Exception as err:
        print(
            f"{err}\n"
            "❌ 错误，请查看运行日志！"
        )

    return msg[:-1]


if __name__ == "__main__":
    print(
        "----------夸克网盘开始签到----------"
    )

    try:
        main()

    except Exception as err:
        print(
            f"\n❌ 签到程序执行失败: "
            f"{type(err).__name__}: {err}"
        )

        print(
            "----------夸克网盘签到失败----------"
        )

        # 返回非 0 状态码，让 GitHub Actions 正确显示失败。
        sys.exit(1)

    print(
        "----------夸克网盘签到完毕----------"
    )
