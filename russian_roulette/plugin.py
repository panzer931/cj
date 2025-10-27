import random
import asyncio
from typing import List, Tuple, Type, Optional, Dict
from datetime import datetime
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    ComponentInfo,
    ConfigField,
    get_logger,
    chat_api,
)

logger = get_logger("russian_roulette")


class DialogueManager:
    """对话管理器 - 管理游戏中的各种对话模板"""
    
    def __init__(self, config_getter):
        """初始化对话管理器
        
        Args:
            config_getter: 配置获取函数
        """
        self.get_config = config_getter
        # 用于跟踪每个群组已使用的台词
        self.used_messages = {}  # Dict[str, Set[int]]
    
    def get_start_message(self) -> str:
        """获取游戏启动消息"""
        return self.get_config("dialogue.start_message", 
                              "哈哈，捡到一把俄罗斯左轮手枪啦，有没有胆肥的勇士，请说麦麦开枪来开始游戏，中枪的就要禁言哦")
    
    def get_random_empty_bullet_message(self, group_id: str, user_name: str) -> str:
        """获取不重复的随机空子弹消息
        
        Args:
            group_id: 群组ID
            user_name: 用户名
            
        Returns:
            str: 格式化后的空子弹消息
        """
        messages = self.get_config("dialogue.empty_bullet_messages", [
            "嘿嘿，我要开枪咯，左轮手枪指着{user_name}，扣动扳机，咔咔，没有打中，你真好彩哎",
            "哦豁，又一个不怕死的，左轮手枪指着{user_name}，扣动扳机，咔咔，没有打中，嘿嘿，你有没有吓破胆",
            "我麦麦神枪手可从来没有失过手，左轮手枪指着{user_name}，猛烈扣下扳机，咔咔，没有打中，命真大啊",
            "想尿裤子就尽情的尿吧，左轮手枪猛的指着{user_name}，咔咔，没有打中",
            "我想吃牛肉面了，但你的牛肉面有葱花，左轮手枪迅速指着{user_name}的头，扣动扳机，咔咔，没有打中，哎呀其实有葱花的更香"
        ])
        
        # 获取该群组已使用的消息索引
        if group_id not in self.used_messages:
            self.used_messages[group_id] = set()
        
        used_indices = self.used_messages[group_id]
        
        # 获取未使用的消息索引
        available_indices = [i for i in range(len(messages)) if i not in used_indices]
        
        # 如果所有消息都用完了，重置
        if not available_indices:
            self.used_messages[group_id] = set()
            available_indices = list(range(len(messages)))
        
        # 随机选择一个未使用的消息
        selected_index = random.choice(available_indices)
        self.used_messages[group_id].add(selected_index)
        
        selected_message = messages[selected_index]
        
        # 格式化消息（使用用户名而非CQ码）
        return selected_message.format(user_name=user_name)
    
    def get_hit_message(self, user_name: str) -> str:
        """获取中弹消息
        
        Args:
            user_name: 用户名
            
        Returns:
            str: 格式化后的中弹消息
        """
        message = self.get_config("dialogue.hit_message", 
                                 "我看你乌云盖顶呢，你确定要玩这游戏，左轮手枪迅速指着{user_name}扣动扳机，砰！鲜血染红了墙壁！")
        
        # 格式化消息（使用用户名而非CQ码）
        return message.format(user_name=user_name)
    
    def clear_used_messages(self, group_id: str):
        """清理群组的已使用消息记录
        
        Args:
            group_id: 群组ID
        """
        if group_id in self.used_messages:
            del self.used_messages[group_id]


class RouletteStartCommand(BaseCommand):
    """麦麦轮盘游戏启动命令 - 启动俄罗斯轮盘游戏"""

    command_name = "roulette_start"
    command_description = "启动麦麦轮盘游戏"
    command_pattern = r"^麦麦轮盘$"
    command_help = "使用方法: 使用指令\"麦麦轮盘\" - 启动游戏，然后使用\"麦麦开枪\"参与"
    command_examples = ["麦麦轮盘"]
    intercept_message = True  # 拦截消息，不让其他组件处理

    # 类级别的游戏数据存储
    game_data: Dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 统一读取游戏配置参数
        self.max_wait_time = self.get_config("game_constants.max_wait_time", 120)
        self.log_prefix = self.get_config("logging.prefix", "[russian_roulette]")
        # 初始化对话管理器
        self.dialogue_manager = DialogueManager(self.get_config)

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行麦麦轮盘游戏启动命令"""
        try:
            logger.info(f"{self.log_prefix} 开始执行麦麦轮盘游戏启动命令")

            # 获取当前聊天流信息
            logger.info(f"{self.log_prefix} 尝试获取聊天流信息")
            chat_stream = self.message.chat_stream
            if not chat_stream:
                logger.info(f"{self.log_prefix} 获取聊天流信息失败")
                await self.send_text("获取聊天信息失败")
                return False, "获取聊天信息失败", True

            # 检查是否在群聊中
            if chat_api.get_stream_type(chat_stream) != "group":
                await self.send_text("英雄的对决需要一个舞台，这场游戏只能在群聊的竞技场中上演。")
                return False, "非群聊环境", True

            # 获取群组信息
            group_id = str(chat_stream.group_info.group_id)

            # 检查是否有正在进行的游戏
            game_key = f"{group_id}"
            current_time = datetime.now()
            
            if game_key in self.game_data:
                game = self.game_data[game_key]
                # 检查游戏是否仍然活跃
                if not game.get("is_active", False):
                    # 游戏已经结束，清理数据并允许重新开始
                    logger.info(f"{self.log_prefix} 发现已结束的游戏数据，清理后重新开始")
                    del self.game_data[game_key]
                else:
                    # 游戏仍在进行中，检查是否超时
                    elapsed_time = (current_time - game["start_time"]).total_seconds()
                    logger.info(f"{self.log_prefix} 游戏已进行 {elapsed_time} 秒")
                    
                    if elapsed_time > self.max_wait_time:
                        logger.info(f"{self.log_prefix} 游戏超时，重置游戏状态")
                        del self.game_data[game_key]
                    else:
                        await self.send_text("游戏已经在进行中，请使用\"麦麦开枪\"参与游戏！")
                        return False, "游戏已在进行", True

            # 创建新游戏并初始化游戏数据
            self.game_data[game_key] = {
                "start_time": current_time,
                "shots": [],  # 记录开枪记录
                "is_active": True,
                "total_shots": 0  # 总开枪次数
            }
            
            # 清理该群组的已使用消息记录
            self.dialogue_manager.clear_used_messages(group_id)
            
            logger.info(f"{self.log_prefix} 游戏初始化完成")

            # 设置检查游戏状态的任务
            asyncio.create_task(self._check_game_timeout(group_id))

            # 使用DialogueManager获取启动消息
            start_message = self.dialogue_manager.get_start_message()
            await self.send_text(start_message)

            logger.info(f"{self.log_prefix} 游戏启动成功，群组: {group_id}")
            return True, "游戏启动成功", True

        except Exception as e:
            logger.error(f"{self.log_prefix} 执行游戏启动命令时发生错误: {str(e)}", exc_info=True)
            await self.send_text(f"发生错误：{str(e)}")
            return False, str(e), True

    async def _check_game_timeout(self, group_id: str):
        """检查游戏是否超时"""
        logger.info(f"{self.log_prefix} 开始检查游戏超时 (群组: {group_id})")
        logger.info(f"{self.log_prefix} 等待 {self.max_wait_time} 秒后检查游戏状态")
        remaining_time = self.max_wait_time
        logger.info(f"{self.log_prefix} 开始计时，每30秒记录一次状态，最后30秒内每10秒记录一次")

        # 记录剩余时间
        while remaining_time > 0:
            # 当剩余时间小于30秒时，每10秒记录一次
            log_interval = min(10 if remaining_time <= 30 else 30, remaining_time)
            await asyncio.sleep(log_interval)
            remaining_time -= log_interval

            if group_id in self.game_data:
                shots = self.game_data[group_id]["shots"]
                shots_count = len(shots)
                # 格式化开枪记录信息
                shots_info = "\n".join([
                    f"  - {s['user_name']}({s['user_id']}) at {s['shot_time'].strftime('%H:%M:%S')}"
                    for s in shots
                ])
                formatted_remaining_time = self._format_duration(remaining_time)
                logger.info(
                    f"{self.log_prefix} 游戏状态更新:\n"
                    f"群组:{group_id}\n"
                    f"剩余时间: {formatted_remaining_time}\n"
                    f"当前开枪次数: {shots_count}\n"
                    f"开枪记录:\n{shots_info}"
                )

        if group_id in self.game_data:
            game = self.game_data[group_id]
            # 检查游戏是否仍然活跃（没有人中弹结束游戏）
            if game.get("is_active", False):
                # 游戏仍在进行中，发送菜鸡消息
                await self.send_text("没人继续玩吗，看来在座的都是菜鸡！")
                logger.info(f"{self.log_prefix} 游戏超时结束，没有人中弹")
            else:
                # 游戏已经结束（有人中弹），不做任何操作
                logger.info(f"{self.log_prefix} 游戏已结束，超时检查无需操作")
            
            # 清理游戏数据
            del self.game_data[group_id]



    def _format_duration(self, seconds: int) -> str:
        """将秒数格式化为可读的时间字符串"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                return f"{minutes}分{remaining_seconds}秒"
            else:
                return f"{minutes}分钟"
        elif seconds < 86400:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes > 0:
                return f"{hours}小时{remaining_minutes}分钟"
            else:
                return f"{hours}小时"
        else:
            days = seconds // 86400
            remaining_hours = (seconds % 86400) // 3600
            if remaining_hours > 0:
                return f"{days}天{remaining_hours}小时"
            else:
                return f"{days}天"


class RouletteShootCommand(BaseCommand):
    """麦麦开枪命令 - 参与俄罗斯轮盘游戏"""

    command_name = "roulette_shoot"
    command_description = "参与麦麦轮盘游戏，进行开枪"
    command_pattern = r"^麦麦开枪$"
    command_help = "使用方法: 先使用\"麦麦轮盘\"启动游戏，然后使用\"麦麦开枪\"参与游戏"
    command_examples = ["麦麦开枪"]
    intercept_message = True  # 拦截消息，不让其他组件处理

    # 使用RouletteStartCommand的游戏数据存储
    @property
    def game_data(self):
        return RouletteStartCommand.game_data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 统一读取游戏配置参数
        self.min_mute_time = self.get_config("game_constants.min_mute_time", 60)
        self.max_mute_time = self.get_config("game_constants.max_mute_time", 3600)
        self.log_prefix = self.get_config("logging.prefix", "[russian_roulette]")
        # 初始化对话管理器
        self.dialogue_manager = DialogueManager(self.get_config)

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行麦麦开枪命令"""
        try:
            logger.info(f"{self.log_prefix} 开始执行麦麦开枪命令")

            # 获取当前聊天流信息
            chat_stream = self.message.chat_stream
            if not chat_stream:
                logger.info(f"{self.log_prefix} 获取聊天流信息失败")
                await self.send_text("获取聊天信息失败")
                return False, "获取聊天信息失败", True

            # 检查是否在群聊中
            if chat_api.get_stream_type(chat_stream) != "group":
                await self.send_text("英雄的对决需要一个舞台，这场游戏只能在群聊的竞技场中上演。")
                return False, "非群聊环境", True

            # 获取用户及群组信息
            user_id = str(chat_stream.user_info.user_id)
            user_name = chat_stream.user_info.user_nickname
            group_id = str(chat_stream.group_info.group_id)

            # 检查游戏是否已启动
            game_key = f"{group_id}"
            if game_key not in self.game_data:
                await self.send_text("还没有启动游戏呢！请先使用\"麦麦轮盘\"启动游戏。")
                return False, "游戏未启动", True

            # 检查游戏是否仍然活跃
            if not self.game_data[game_key].get("is_active", False):
                await self.send_text("游戏已经结束了，请使用\"麦麦轮盘\"重新启动游戏。")
                return False, "游戏已结束", True

            # 增加总开枪次数
            self.game_data[game_key]["total_shots"] += 1
            current_shot = self.game_data[game_key]["total_shots"]

            # 检查是否超过最大开枪次数（6枪）
            if current_shot > 6:
                await self.send_text("游戏已经结束了，左轮手枪的6发子弹都已经打完。")
                self.game_data[game_key]["is_active"] = False
                return False, "游戏已结束", True

            # 记录用户开枪
            shot_record = {
                "user_id": user_id,
                "user_name": user_name,
                "shot_time": datetime.now(),
                "shot_number": current_shot
            }
            self.game_data[game_key]["shots"].append(shot_record)

            # 计算当前中弹概率：剩余子弹中有1发实弹
            remaining_bullets = 6 - current_shot + 1  # 包括当前这一枪
            hit_probability = 1 / remaining_bullets
            
            # 根据概率判断是否中弹
            random_number = random.random()
            is_hit = (random_number < hit_probability)
            
            logger.info(f"{self.log_prefix} 第{current_shot}枪，中弹概率: {hit_probability:.3f} ({hit_probability:.1%})，随机数: {random_number:.3f}，结果: {'中弹' if is_hit else '空弹'}")

            if is_hit:
                # 中弹情况
                hit_message = self.dialogue_manager.get_hit_message(user_name)
                await self.send_text(hit_message)
                
                # 执行禁言
                await self._execute_mute(user_id, user_name)
                
                # 游戏结束，清理状态
                self.game_data[game_key]["is_active"] = False
                # 清理该群组的已使用消息记录
                self.dialogue_manager.clear_used_messages(group_id)
                logger.info(f"{self.log_prefix} 游戏结束，用户 {user_name} 中弹，第{current_shot}枪")
                
                return True, "中弹游戏结束", True
            else:
                # 空子弹情况 - 使用不重复的随机台词
                empty_message = self.dialogue_manager.get_random_empty_bullet_message(group_id, user_name)
                await self.send_text(empty_message)
                
                # 如果是第6枪还没中，那下一枪必中（但这种情况理论上不会发生）
                if current_shot == 6:
                    await self.send_text("这不可能！第6枪必定中弹！")
                    self.game_data[game_key]["is_active"] = False
                
                return True, "空子弹继续游戏", True

        except Exception as e:
            logger.error(f"{self.log_prefix} 执行开枪命令时发生错误: {str(e)}", exc_info=True)
            await self.send_text(f"发生错误：{str(e)}")
            return False, str(e), True

    async def _execute_mute(self, user_id: str, user_name: str):
        """执行禁言操作"""
        try:
            # 随机禁言时间（秒）
            mute_seconds = random.randint(self.min_mute_time, self.max_mute_time)
            formatted_duration = self._format_duration(mute_seconds)

            logger.info(f"{self.log_prefix} 开始执行禁言操作，用户: {user_name}, 禁言时间: {formatted_duration}")
            
            # 执行禁言
            success = await self.send_command(
                command_name="GROUP_BAN",
                args={
                    "qq_id": str(user_id),
                    "duration": str(mute_seconds)
                },
                storage_message=False
            )

            if not success:
                error_msg = "发送禁言命令失败"
                logger.warning(f"{self.log_prefix} {error_msg}")
                await self.send_text("执行禁言操作失败")
            else:
                await self.send_text(f"命运无常，@{user_name} 将在{formatted_duration}的沉默中回味这一刻。")

        except Exception as e:
            logger.error(f"{self.log_prefix} 执行禁言时发生错误: {str(e)}", exc_info=True)
            await self.send_text(f"执行禁言时发生错误：{str(e)}")

    def _format_duration(self, seconds: int) -> str:
        """将秒数格式化为可读的时间字符串"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds > 0:
                return f"{minutes}分{remaining_seconds}秒"
            else:
                return f"{minutes}分钟"
        elif seconds < 86400:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes > 0:
                return f"{hours}小时{remaining_minutes}分钟"
            else:
                return f"{hours}小时"
        else:
            days = seconds // 86400
            remaining_hours = (seconds % 86400) // 3600
            if remaining_hours > 0:
                return f"{days}天{remaining_hours}小时"
            else:
                return f"{days}天"


@register_plugin
class RussianRoulettePlugin(BasePlugin):
    """麦麦轮盘游戏插件
    
    在命运的舞台上，勇士们围坐一圈，手中紧握那把只装有一颗子弹的左轮手枪。
    每一次扣动扳机，都是对勇气与命运的挑战。
    
    功能特性:
    - 支持多人参与的开枪游戏
    - 支持自动禁言参与者
    - 支持游戏超时自动结束
    - 支持游戏状态检查
    - 完整的错误处理
    - 日志记录和监控
    """

    # 插件基本信息
    plugin_name: str = "russian_roulette"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "game_constants": "游戏常量配置",
        "dialogue": "对话配置",
        "logging": "日志记录配置",
    }

    # 配置Schema定义
    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.1.0", description="插件配置文件版本号"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        # 游戏常量配置
        "game_constants": {
            "max_wait_time": ConfigField(type=int, default=120, description="最大等待时间（秒）"),
            "max_participants": ConfigField(type=int, default=6, description="最大参与人数"),
            "min_mute_time": ConfigField(type=int, default=60, description="最小禁言时间（秒）"),
            "max_mute_time": ConfigField(type=int, default=3600, description="最大禁言时间（秒）"),
        },
        # 对话配置
        "dialogue": {
            "start_message": ConfigField(
                type=str, 
                default="哈哈，捡到一把俄罗斯左轮手枪啦，有没有胆肥的勇士，请说麦麦开枪来开始游戏，中枪的就要禁言哦", 
                description="游戏启动消息"
            ),
            "empty_bullet_messages": ConfigField(
                type=list, 
                default=[
                    "嘿嘿，我要开枪咯，左轮手枪指着{user_name}，扣动扳机，咔咔，没有打中，你真好彩哎",
                    "哦豁，又一个不怕死的，左轮手枪指着{user_name}，扣动扳机，咔咔，没有打中，嘿嘿，你有没有吓破胆",
                    "我麦麦神枪手可从来没有失过手，左轮手枪指着{user_name}，猛烈扣下扳机，咔咔，没有打中，命真大啊",
                    "想尿裤子就尽情的尿吧，左轮手枪猛的指着{user_name}，咔咔，没有打中",
                    "我想吃牛肉面了，但你的牛肉面有葱花，左轮手枪迅速指着{user_name}的头，扣动扳机，咔咔，没有打中，哎呀其实有葱花的更香"
                ], 
                description="空子弹不重复随机对话列表"
            ),
            "hit_message": ConfigField(
                type=str, 
                default="我看你乌云盖顶呢，你确定要玩这游戏，左轮手枪迅速指着{user_name}扣动扳机，砰！鲜血染红了墙壁！", 
                description="中弹消息"
            ),
        },
        "logging": {
            "level": ConfigField(
                type=str, default="INFO", description="日志级别", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            "prefix": ConfigField(type=str, default="[russian_roulette]", description="日志前缀"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        return [
            (RouletteStartCommand.get_command_info(), RouletteStartCommand),
            (RouletteShootCommand.get_command_info(), RouletteShootCommand),
        ]