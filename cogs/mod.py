import json
import math
import datetime

import discord
from discord.ext import commands

from cogs.utils.cExceptions import *
from cogs.utils.loggerEntry import *
from cogs.utils.modUtils import ModUtils
from cogs.utils.database import Database


def is_user():
    def pred(ctx):
        if isinstance(ctx.channel, discord.DMChannel):
            raise commands.NoPrivateMessage()  # We assume any command with perms check can't be used in DMs
        cmd = str(ctx.command)
        cmd = "warn" if cmd == "warns" else cmd
        author = ctx.author
        user_roles = [r.id for r in author.roles]

        with open('./jsons/permissions.json') as f:
            perms = json.load(f)

        try:
            cmd_roles = perms[cmd]
        except KeyError:
            """
            If the cummand is not in the JSON file, assume everyone has access,
            including standard members. (This is useful for fun commands, where
            they do not modify the server in any way, and saves you time by not
            writing them in the file.)
            """
            return True
        else:
            """
            Else if the command *is* in the JSON file, and there is no blacklisted
            roles specified, everyone who can access the bot in general (i.e.
            moderators, etc.) can use it. But still not normal users. (This is good
            for commands like ban, unban, or just cummands that you want anyone who
            has access to the bot to use, but not *everyone* in the *server*.)
            """
            # Check if the user is a moderator:
            for r_id in user_roles:
                if r_id in perms['moderator_role_ids']:
                    for _r_id in user_roles:
                        if _r_id in cmd_roles:
                            perms = f'"USE_{cmd.upper()}"'
                            print("debug: missing perms for " + cmd)
                            raise MissingPermissions(perms)
                    return True
            print("debug: not allowed access to the bot for " + cmd)
            raise NoAccess(f"You are not authorized to use `{ctx.me.name}` at this time.")

    return commands.check(pred)


class Moderator(commands.Cog, ModUtils):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot
        self.pagination_amt = 5
        self.muted_role = self.get_role("muted_role")
        self.kenneled_role = self.get_role("kenneled_role")
        self.kenneled_channel = self.get_channel("kenneled_channel")
        self.db = Database('./dbs/reminders.db')

    async def add_reminder(self, author, channel, delta, message):
       """
       Adds a reminder to the database.

       Parameters
       -----------
       author: :class:`discord.Member`
           The author of the reminder.
       channel: :class:`discord.Channel`
           The channel of the reminder.
       delta: :class:`datetime.datetime`
           The date to initiate the reminder.
       message: :class:`str`
           The message of the reminder.
       """

       await self.db.execute(
           "INSERT INTO reminders (author, channel, delta, message) "
           "VALUES(?, ?, ?, ?)",
           (author.id, channel.id, delta, message)
       )    
    
    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_tables()

    @commands.command(description="Change bot prefix.")
    @is_user()
    async def update_prefix(self, ctx, prefix):
        """ Change bot prefix. """
        with open('./jsons/prefixes.json') as f:
            prefixes = json.load(f)

        prefixes[str(ctx.guild.id)] = prefix

        with open('./jsons/prefixes.json', 'w') as f:
            json.dump(prefixes, f, indent=4)

    @commands.command(description="Adds or removes roles specified to/from a user.")
    @is_user()
    async def role(self, ctx, user : discord.Member , *args):
        """Adds removes or toggles roles for a user"""
        # parse roles to add or remove based on dyno syntax
        roles = ' '.join(args)
        roles = [r.strip() for r in roles.split(',')]
        roles_mentioned = [r[1:].lower() for r in roles if r.startswith('+') or r.startswith('-')]
        roles_mentioned += [r.lower() for r in roles if not (r.startswith('+') or r.startswith('-'))]
        roles_mentioned = list(set(roles_mentioned))
        roles_to_add = [r[1:].lower() for r in roles if r.startswith('+')]
        roles_to_remove = [r[1:].lower() for r in roles if r.startswith('-')]
        roles = [r.lower() for r in roles_mentioned if r.lower() not in roles_to_add or r.lower() not in roles_to_remove]
        # get user, current roles
        user_id = user.id
        user_to_change = user
        if user_to_change:
            user_has = [r.name.lower() for r in user_to_change.roles]
            roles_to_add += [r for r in roles if r.lower() not in user_has and r.lower() not in roles_to_add]
            roles_to_remove += [r for r in roles if r.lower() in user_has and r.lower() not in roles_to_remove and r.lower() not in roles_to_add]
            roles_to_add = [r for r in roles_to_add if r.lower() not in roles_to_remove]
            failed_roles = []
            msg = 'Made the following changes to ' + user_to_change.name + '#' + user_to_change.discriminator + ': '
            add_roles = []
            remove_roles = []
            for role in roles_to_add:
                role_to_add = discord.utils.find(lambda m: m.name.lower() == role, ctx.guild.roles)
                if role_to_add and role_to_add < ctx.guild.me.top_role:
                    msg += '+' + role_to_add.name + ', '
                    add_roles.append(role_to_add)
                else:
                    failed_roles.append(role)

            for role in roles_to_remove:
                role_to_remove = discord.utils.find(lambda m: m.name.lower() == role, ctx.guild.roles)
                if role_to_remove and role_to_remove < ctx.guild.me.top_role:
                    msg += '-' + role_to_remove.name + ', '
                    remove_roles.append(role_to_remove)
                else:
                    failed_roles.append(role)
            try:
                await user_to_change.add_roles(*add_roles)
                await user_to_change.remove_roles(*remove_roles)
            except discord.Forbidden:
                await ctx.channel.send('I don\'t have the proper permissions!')
            except discord.HTTPException:
                await ctx.channel.send('Failed to change roles!')
            else:
                if not add_roles and not remove_roles:
                    await ctx.channel.send('No changes made!')
                else:
                    if failed_roles:
                        msg = msg[:-2] + '\nFailed to change roles: ' + ', '.join(failed_roles)
                    else:
                        msg = msg[:-2]
                    await ctx.channel.send(msg)
            logged_entry = f"{ctx.author.mention} used role command on {user_to_change.mention}"
            await self.log_entry(
                ctx,
                description=logged_entry,
                entry_type=RoleUpdate
            )
                    

    @commands.command(description="Mute a user and remove all their roles.")
    @is_user()
    async def mute(self, ctx, user: discord.Member, *, reason="No reason given."):
        """ Mute a user and remove all their roles. """
        author = ctx.author
        guild = ctx.guild
        channel = ctx.channel
        if await self.is_muted(user):
            await ctx.send(
                "That user is already muted!"
            )
        else:
            muted = guild.get_role(self.muted_role)
            user_roles = [
                r for r in user.roles if r < guild.me.top_role
                                         and not (r.is_default() or r.managed)
            ]
            if len(user_roles) > 0:
                await user.remove_roles(*user_roles, reason="Muting user...")
            await self.add_muted(user, user_roles)
            await user.add_roles(muted, reason=reason)
            await channel.send('User muted! Set a reminder to remind you to unmute!')
            identifier = await self.generate_id()
            await self.log_warn(identifier, user, author, f"(Auto-warn: type `mute`) - {reason}")

            try:
                await user.send(
                    f"You were muted in **`{guild}`** for **`{reason}`**"
                )
            except discord.Forbidden:
                pass

            logged_entry = f"{author.mention} Muted {user.mention} for {reason}"
            await self.log_entry(
                ctx,
                description=logged_entry,
                entry_type=Mute
            )

    @commands.command(description="Kennel a user and remove all their roles.")
    @is_user()
    async def kennel(self, ctx, user: discord.Member, *, reason="No reason given."):
        """ Kennel a user and remove all their roles. """
        author = ctx.author
        guild = ctx.guild
        channel = ctx.channel
        if await self.is_kenneled(user):
            await ctx.send(
                "That user is already kenneled!"
            )
        else:
            kenneled = guild.get_role(self.kenneled_role)
            user_roles = [
                r for r in user.roles if r < guild.me.top_role
                                         and not (r.is_default() or r.managed)
            ]
            if len(user_roles) > 0:
                await user.remove_roles(*user_roles, reason="Kenneling user...")
            await self.add_kenneled(user, user_roles)
            await user.add_roles(kenneled, reason=reason)
            await channel.send('User kenneled! Set a reminder to remind you to unmute!')
            identifier = await self.generate_id()
            await self.log_warn(identifier, user, author, f"(Auto-warn: type `kennel`) - {reason}")

            try:
                await user.send(
                    f"You were kenneled in **`{guild}`** for **`{reason}`**\n"
                    f"Please check out the **<#{self.kenneled_channel}>** for more information."
                )
            except discord.Forbidden:
                pass

            logged_entry = f"{author.mention} kenneled {user.mention} for {reason}"
            await self.log_entry(
                ctx,
                description=logged_entry,
                entry_type=Kennel
            )

    @commands.command(description="Unmute a user and return all their roles.")
    @is_user()
    async def unmute(self, ctx, user: discord.Member, *, reason='No reason given.'):
        """ Unmute a user and return all their roles. """
        author = ctx.author
        guild = ctx.guild
        muted = guild.get_role(self.muted_role)
        await user.remove_roles(muted)

        if await self.is_muted(user):
            _roles = await self.get_muted_roles(user)  # Get role IDs from muted user
            roles = [guild.get_role(r[0]) for r in _roles]

            await self.remove_muted(user)
            if any(roles):
                await user.add_roles(*roles)

            await ctx.send("Unmuted that user.")

            try:
                await user.send(f"You were unmuted in **`{guild}`**.")
            except discord.Forbidden:
                pass

            await self.log_entry(
                ctx,
                description=f"**{author}** ({author.mention}) `unkenneled` **{user}** ({user.mention}).\n"
                            f"**Reason:** `{reason}`.",
                entry_type=Unmute
            )
        else:
            await ctx.send(f"{author.mention}, that user was not muted!")

    @commands.command(description="Unkennel a user and return all of their roles.")
    @is_user()
    async def unkennel(self, ctx, user: discord.Member, *, reason='No reason given.'):
        """ Unkennel a user and return all of their roles. """
        author = ctx.author
        guild = ctx.guild
        kenneled = guild.get_role(self.kenneled_role)
        await user.remove_roles(kenneled)

        if await self.is_kenneled(user):
            # Get role IDs from muted user
            _roles = await self.get_kenneled_roles(user)
            roles = [guild.get_role(r[0]) for r in _roles]

            await self.remove_kenneled(user)
            if any(roles):
                await user.add_roles(*roles)

            await ctx.send("Unkenneled that user.")

            try:
                await user.send(f"You were unkenneled in **`{guild}`**.")
            except discord.Forbidden:
                pass

            logged_entry = f"`{author}` ({author.mention}) unkenneled `{user}` ({user.mention})\n`reason:` {reason}"
            await self.log_entry(
                ctx,
                description=logged_entry,
                entry_type=Unkennel
            )
        else:
            await ctx.send(f"{author.mention}, that user was not kenneled!")

    @commands.command(description="Shorthand version to `$warn getall (user)`. List all warns from a user.")
    @is_user()
    async def warns(self, ctx, user: discord.Member):
        """ Shorthand version to `$warn getall (user)`. List all warns from a user. """
        await self.getall(ctx, user)

    @commands.group(description="Handles all warn-related commands. Type '$help warn' for more information.")
    @is_user()
    async def warn(self, ctx):
        """ Handles all warn-related commands. """
        if ctx.invoked_subcommand is None:
            cmd = self.bot.get_command("warn add")
            # Get new ctx since the old one had removed user param from params because it thinks that's the sub-command
            new_ctx = await self.bot.get_context(ctx.message)
            await cmd.invoke(new_ctx)

    @warn.command(description="Adds a new warn to the user.")
    async def add(self, ctx, user: discord.Member, *, reason='No reason given.'):
        """ Adds a new warn to the user. """
        author = ctx.author
        guild = ctx.guild
        identifier = await self.generate_id()
        await self.log_warn(identifier, user, author, reason)
        await ctx.send(
            f"User {user.mention} was warned for {reason} and with a log ID of `{identifier}`."
        )

        try:
            await user.send(
                f"You were warned in **`{guild}`** for **`{reason}`**"
            )
        except discord.Forbidden:
            pass

        await self.log_entry(
            ctx,
            description=f"{author.mention} Warned {user.mention} for {reason}"
                        f" and with a log ID of `{identifier}`",
            entry_type=Warn
        )

    @warn.command(aliases=['fetch', 'grab', 'list'], description="Get a warn via specified ID.")
    async def get(self, ctx, identifier):
        """ Get a warn via specified ID. """
        ret = await self.fetch_warn(identifier)
        if ret:
            user_id, author_id, reason, date = ret
            user = await self.get_user(user_id)
            author = await self.get_user(author_id)
            embed = discord.Embed(
                title=f"Warn retrieved with ID of {identifier}:",
                timestamp=self.strptime(date),
                color=discord.Color(0xe62169)
            )
            embed.add_field(
                name='User:',
                value=f"{user.id} ({user.mention})",
                inline=False
            )
            embed.add_field(
                name='Reason:',
                value=reason,
                inline=False
            )
            embed.add_field(
                name='Issuer:',
                value=f"{author.id} ({author.mention})",
                inline=False
            )
            embed.set_footer(
                text="Warn issued on ->"
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"No warn found with ID {identifier}.")

    @warn.command(aliases=['del', 'rem'], description="Delete a warn via specified ID.")
    @commands.has_role(709598174314233888)
    async def remove(self, ctx, identifier):
        """ Delete a warn via specified ID. """
        ret = await self.delete_warn(identifier)
        if ret:
            await ctx.send(f"Deleted the warn with ID {identifier}.")
        else:
            await ctx.send(f"No warn found with ID {identifier}.")

    @warn.command(aliases=['change', 'cng'], description="Edit a specified warn's [reason].")
    async def edit(self, ctx, identifier, *, reason):
        """ Edit a specified warn's [reason]. """
        ret = await self.change_warn(identifier, reason)
        if ret:
            await ctx.send(f"Edited warn `#{identifier}` to `{reason}`.")
        else:
            await ctx.send(f"No warn found with ID {identifier}.")

    @warn.command(aliases=['fetchall', 'graball', 'listall'], description="List all warns of a user.")
    async def getall(self, ctx, user: discord.Member):
        """ List all warns of a user. """
        warns = await self.fetch_user_warns(user)
        author = None
        embed = discord.Embed(
            title=f'Fetching warns for `{user}`...',
            description=f"{len(warns)} warns in total for this user.",
            timestamp=self.now,
            color=discord.Color(0xe62169)
        )
        for entry, warn in enumerate(warns):
            warn_id, warn_author, warn_reason, warn_ts = warn
            ts = self.strptime(warn_ts)
            formatted = ts.strftime("%b %d, %Y at %I:%M:%S %p (UTC-0)")
            author = await self.get_user(warn_author)

            embed.add_field(
                name=f'Entry #{entry + 1}:',
                value=f"**`ID:`** #{warn_id}\n"
                      f"**`Issuer:`** {author.id} ({author.mention})\n"
                      f"**`Reason:`** {warn_reason}\n"
                      f"**`Occurred on:`** {formatted}",
                inline=False
            )
            total = math.ceil(len(embed.fields) / self.pagination_amt)
            embed.set_footer(text=f"Page 1 of {total}")

        if len(embed.fields) > 0:
            _embed = embed.copy()
            _embed._fields = _embed._fields[:self.pagination_amt]
            msg = await ctx.send(embed=_embed)
            await self.paginate(msg, author, embed)
        else:
            await ctx.send(f"No warns were found for {user.mention}.")
    
    @commands.command(description='Warn a user for a ToS/Rulebreaking pfp, status, or username. \n Valid types are nsfw, hitler, status, or name')
    @is_user()
    async def notify(self, ctx, type : str, user : discord.Member):
        if type.lower() == 'nsfw' or type.lower() == 'pfp':
            msg = 'We noticed you have a NSFW profile picture. We do not allow this as it violates Discord ToS. If you don\'' \
                + 't change it within 24 hours we will have no choice but to ban you from the server until you have a SFW '\
                + 'icon. Thanks for understanding ^^ - <@' + str(ctx.author.id) + '> at /r/yiff'
            reason = 'NSFW pfp'
        elif type.lower() == 'hitler':
            msg = 'We noticed you have a rulebreaking profile picture. We do not allow this as it violates server rules on allowable images. If you don\'' \
                  + 't change it within 24 hours we will have no choice but to ban you from the server until you have an acceptable ' \
                  + 'icon. Thanks for understanding ^^ - <@' + str(ctx.author.id) + '> at /r/yiff'
            reason = 'rulebreaking pfp'
        elif type.lower() == 'status':
            msg = 'We noticed you have a rulebreaking Discord status. We do not allow this as it violates server rules on allowable content. If you don\'' \
                  + 't change it within 24 hours we will have no choice but to ban you from the server until you have an acceptable ' \
                  + 'status. Thanks for understanding ^^ - <@' + str(ctx.author.id) + '> at /r/yiff'
            reason = 'status'
        elif type.lower() == 'name' or type.lower() == 'nickname' or type.lower() == 'nick':
            msg = 'We noticed you have a rulebreaking Discord name or nickname. We do not allow this as it violates server rules on allowable content. If you don\'' \
                  + 't change it within 24 hours we will have no choice but to ban you from the server until you have an acceptable ' \
                  + 'name or nickname. Thanks for understanding ^^ - <@' + str(ctx.author.id) + '> at /r/yiff'
            reason = 'name/nickname'
        else:
            await ctx.channel.send('Invalid warn type given! Try one of these: `nsfw`, `hitler`, `status`, `name`, `custom`!')
            return
        try:
            await user.send(msg)
        except (discord.HTTPException, discord.Forbidden):
            await ctx.channel.send('Could not send DM!')
        else:
            await ctx.channel.send('User ' + user.name + '#' + user.discriminator + ' notified!')
        embed_text = '<@' + str(
            ctx.author.id) + '> ' + ctx.author.name + '#' + ctx.author.discriminator + ' used `$notify` command on <@'\
            + str(user.id) + '> ' + user.name + '#' + user.discriminator + '\nReason: ' + reason
        await self.log_entry(
            ctx,
            description=embed_text,
            entry_type=Notify
        )
        reminder_text = 'Check on <@' + str(user.id) + '>\'s ' + reason + '!'
        dt_td = datetime.timedelta(seconds=86400)
        delta = self.now + dt_td
        await self.add_reminder(
            ctx.author,
            ctx.channel,
            delta.replace(microsecond=0),
            reminder_text
        )
        await ctx.channel.send('Reminder added!')
        
    @commands.command(description="Ban the specified user")
    @is_user()
    async def ban(self, ctx, user : str, *args):
        if user.startswith('<'):
            user = await self.bot.fetch_user(int(user[1:-2]))
        else:
            user = await self.bot.fetch_user(int(user))
        reason = ' '.join(args)
        if not reason:
            reason = "No reason given!"
        await ctx.guild.ban(user, reason=reason)
        await ctx.send(f"{user.mention} banned!")
        
    
    @commands.command(description="Unban the specified user")
    @is_user()
    async def unban(self, ctx, user):
        banned_users = await ctx.guild.bans()
        for ban_entry in banned_users:
            banned_user = ban_entry.user
            if user == banned_user.id or user == banned_user.mention:
                await ctx.guild.unban(banned_user)
                await ctx.send(f"{banned_user.mention} unbanned!")

# below command broke the help embed so it is commented out until it can be addressed
    #@commands.command(description="Run SQL Queries.")
    #@commands.has_permissions(administrator=True)
    #async def run_sql(self, ctx, *, query):
    #    """ Run SQL Queries. """
    #    resp = await self.db.get(
    #        query
    #    )
    #    await ctx.send("Response: {}".format(resp))


def setup(bot):
    bot.add_cog(Moderator(bot))
