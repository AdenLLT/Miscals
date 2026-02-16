ar_flag, (flag_x, flag_y), circular_flag)
                                print(f"✅ Pasted {team_name} flag at ({flag_x}, {flag_y})")
                    except Exception as e:
                        print(f"❌ Error loading team flag: {e}")

            # ========================================
            # PLACE USER AVATAR
            # ========================================
            avatar_x = LAYOUT['avatar_x']
            avatar_y = LAYOUT['avatar_y']
            avatar_size = LAYOUT['avatar_size']

            if user.avatar:
                try:
                    async with session.get(str(user.avatar.url)) as resp:
                        if resp.status == 200:
                            avatar_data = await resp.read()
                            avatar_img = Image.open(io.BytesIO(avatar_data)).convert('RGBA')
                        else:
                            avatar_img = Image.new('RGBA', (avatar_size, avatar_size), (128, 128, 128, 255))
                except:
                    avatar_img = Image.new('RGBA', (avatar_size, avatar_size), (128, 128, 128, 255))
            else:
                avatar_img = Image.new('RGBA', (avatar_size, avatar_size), (128, 128, 128, 255))

            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)

            border_thickness = 6
            bordered_size = avatar_size + (border_thickness * 2)
            bordered_avatar = Image.new('RGBA', (bordered_size, bordered_size), (255, 255, 255, 255))

            border_mask = Image.new('L', (bordered_size, bordered_size), 0)
            border_mask_draw = ImageDraw.Draw(border_mask)
            border_mask_draw.ellipse((0, 0, bordered_size, bordered_size), fill=255)

            bordered_avatar.paste(avatar_img, (border_thickness, border_thickness), mask)

            img.paste(bordered_avatar, (avatar_x - border_thickness, avatar_y - border_thickness), border_mask)
            print(f"✅ Pasted user avatar at ({avatar_x}, {avatar_y})")

            # ========================================
            # PLACE PLAYER IMAGE
            # ========================================
            player_x = LAYOUT['player_x']
            player_y = LAYOUT['player_y']
            player_size = LAYOUT['player_size']

            player_img = None
            if player_data.get('image'):
                try:
                    async with session.get(player_data['image']) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            player_img = Image.open(io.BytesIO(img_data)).convert('RGBA')
                            print("✅ Downloaded player image")
                except Exception as e:
                    print(f"❌ Error downloading player image: {e}")

            if not player_img:
                try:
                    player_img = Image.open("fallback.webp").convert('RGBA')
                    print("✅ Using fallback image")
                except:
                    await interaction.followup.send("❌ Could not load player image!", ephemeral=True)
                    return

            player_img = player_img.resize((player_size, player_size), Image.Resampling.LANCZOS)
            img.paste(player_img, (player_x, player_y), player_img)
            print(f"✅ Pasted player image at ({player_x}, {player_y})")

        # ========================================
        # DRAW ALL TEXT
        # ========================================
        img = img.convert('RGB')
        draw = ImageDraw.Draw(img)

        text_color = LAYOUT['text_color']
        outline_color = LAYOUT['text_outline_color']
        outline_width = LAYOUT['text_outline_width']

        # ========================================
        # Draw Player Name (WITH OUTLINE)
        # ========================================
        player_name_x = LAYOUT['player_name_x']
        player_name_y = LAYOUT['player_name_y']

        # Check if player name is too wide
        current_font = player_name_font
        bbox = draw.textbbox((0, 0), player_name, font=current_font)
        text_width = bbox[2] - bbox[0]

        # Scale down font if text is too wide
        if text_width > LAYOUT['player_name_max_width']:
            scale_factor = LAYOUT['player_name_max_width'] / text_width
            new_size = int(LAYOUT['player_name_size'] * scale_factor)
            try:
                current_font = ImageFont.truetype("nor.otf", new_size)
            except:
                try:
                    current_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", new_size)
                except:
                    current_font = ImageFont.load_default()

        print(f"Drawing player name '{player_name}' at ({player_name_x}, {player_name_y})")

        # Draw outline
        for adj_x in range(-outline_width, outline_width + 1):
            for adj_y in range(-outline_width, outline_width + 1):
                draw.text((player_name_x + adj_x, player_name_y + adj_y), player_name, font=current_font, fill=outline_color)
        # Draw main text
        draw.text((player_name_x, player_name_y), player_name, font=current_font, fill=text_color)

        # ========================================
        # Draw Username (NO OUTLINE)
        # ========================================
        username_text = f"@{user.name}"
        username_x = LAYOUT['username_x']
        username_y = LAYOUT['username_y']

        # Check if username is too wide
        current_username_font = username_font
        bbox = draw.textbbox((0, 0), username_text, font=current_username_font)
        text_width = bbox[2] - bbox[0]

        # Scale down font if text is too wide
        if text_width > LAYOUT['username_max_width']:
            scale_factor = LAYOUT['username_max_width'] / text_width
            new_size = int(LAYOUT['username_size'] * scale_factor)
            try:
                current_username_font = ImageFont.truetype("nor.otf", new_size)
            except:
                try:
                    current_username_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", new_size)
                except:
                    current_username_font = ImageFont.load_default()

        print(f"Drawing username '{username_text}' at ({username_x}, {username_y})")
        draw.text((username_x, username_y), username_text, font=current_username_font, fill=text_color)

        # ========================================
        # Draw Achievement Text (NO OUTLINE, NO WORD WRAP)
        # ========================================
        achievement_x = LAYOUT['achievement_x']
        achievement_y = LAYOUT['achievement_y']

        # Check if achievement text is too wide
        current_achievement_font = text_font
        bbox = draw.textbbox((0, 0), text, font=current_achievement_font)
        text_width = bbox[2] - bbox[0]

        # Scale down font if text is too wide
        if text_width > LAYOUT['achievement_max_width']:
            scale_factor = LAYOUT['achievement_max_width'] / text_width
            new_size = int(LAYOUT['achievement_size'] * scale_factor)
            try:
                current_achievement_font = ImageFont.truetype("nor.otf", new_size)
            except:
                try:
                    current_achievement_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", new_size)
                except:
                    current_achievement_font = ImageFont.load_default()

        print(f"Drawing achievement text '{text}' at ({achievement_x}, {achievement_y})")
        draw.text((achievement_x, achievement_y), text, font=current_achievement_font, fill=text_color)

        # ========================================
        # Draw Team Name (NO OUTLINE)
        # ========================================
        team_name_x = LAYOUT['team_name_x']
        team_name_y = achievement_y + LAYOUT['team_name_spacing']

        print(f"Drawing team name '{team_name}' at ({team_name_x}, {team_name_y})")
        draw.text((team_name_x, team_name_y), team_name, font=team_font, fill=text_color)

        # ========================================
        # SAVE AND SEND
        # ========================================
        output = io.BytesIO()
        img.save(output, format='PNG', quality=95)
        output.seek(0)

        embed = discord.Embed(
            title="🎗️ SPOTLIGHT Perfomance",
            color=get_team_color(team_name)
        )

        embed.set_image(url="attachment://player_of_match.png")
        embed.set_footer(text="CWC HEROES™")

        file = discord.File(output, filename="player_of_match.png")
        message = await interaction.channel.send(embed=embed, file=file)

        # Add fire emoji reaction
        await message.add_reaction("🔥")

        print("✅ Sent image to channel")
