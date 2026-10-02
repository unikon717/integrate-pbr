package dev.integratepbr.client;

import dev.integratepbr.config.MaterialOverrides;
import dev.integratepbr.pack.GeneratedPackManager;
import dev.integratepbr.texture.MaterialType;

import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;
import net.minecraft.client.Minecraft;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.phys.BlockHitResult;
import net.neoforged.neoforge.client.event.RegisterClientCommandsEvent;
import net.neoforged.fml.loading.FMLPaths;

import java.io.IOException;

/** Client-only commands for the held item or the block under the crosshair. */
final class MaterialCommands {
    private MaterialCommands() {}

    static void register(RegisterClientCommandsEvent event) {
        var root = Commands.literal("integratepbr");
        root.then(target("held", MaterialOverrides.Kind.ITEM));
        root.then(target("block", MaterialOverrides.Kind.BLOCK));
        root.then(Commands.literal("review")
                .executes(ctx -> review(ctx.getSource(), 1))
                .then(Commands.argument("page", IntegerArgumentType.integer(1))
                        .executes(ctx -> review(ctx.getSource(), IntegerArgumentType.getInteger(ctx, "page")))));
        event.getDispatcher().register(root);
    }

    private static int review(CommandSourceStack source, int page) {
        var entries = GeneratedPackManager.reviewEntries();
        int pages = Math.max(1, (entries.size() + 7) / 8);
        if (page > pages) {
            source.sendFailure(Component.literal("Only " + pages + " review page(s) available."));
            return 0;
        }
        source.sendSuccess(() -> Component.literal("Integrate PBR: " + entries.size()
                + " uncertain textures; page " + page + "/" + pages
                + ". Full list: resourcepacks/IntegratePBR_Generated/REVIEW.txt"), false);
        for (int index = (page - 1) * 8; index < Math.min(entries.size(), page * 8); index++) {
            String entry = entries.get(index);
            source.sendSuccess(() -> Component.literal(entry), false);
        }
        return 1;
    }

    private static LiteralArgumentBuilder<CommandSourceStack> target(String name, MaterialOverrides.Kind kind) {
        var target = Commands.literal(name);
        target.then(Commands.literal("disable").executes(ctx -> change(ctx.getSource(), kind, "disabled")));
        target.then(Commands.literal("auto").executes(ctx -> change(ctx.getSource(), kind, "auto")));
        target.then(Commands.literal("status").executes(ctx -> change(ctx.getSource(), kind, "status")));
        var type = Commands.literal("type");
        for (MaterialType material : MaterialType.values()) {
            type.then(Commands.literal(material.name().toLowerCase(java.util.Locale.ROOT))
                    .executes(ctx -> change(ctx.getSource(), kind, material.name())));
        }
        target.then(type);
        return target;
    }

    private static int change(CommandSourceStack source, MaterialOverrides.Kind kind, String action) {
        Minecraft minecraft = Minecraft.getInstance();
        if (minecraft.player == null || minecraft.level == null) return 0;
        ResourceLocation id;
        if (kind == MaterialOverrides.Kind.ITEM) {
            var stack = minecraft.player.getMainHandItem();
            if (stack.isEmpty()) {
                source.sendFailure(Component.literal("Hold an item first."));
                return 0;
            }
            id = BuiltInRegistries.ITEM.getKey(stack.getItem());
        } else {
            if (!(minecraft.hitResult instanceof BlockHitResult hit)) {
                source.sendFailure(Component.literal("Look at a block first."));
                return 0;
            }
            id = BuiltInRegistries.BLOCK.getKey(minecraft.level.getBlockState(hit.getBlockPos()).getBlock());
        }
        try {
            var overrides = new MaterialOverrides(FMLPaths.CONFIGDIR.get().resolve("integratepbr-overrides.properties"));
            if (action.equals("auto")) overrides.clear(kind, id);
            else if (action.equals("disabled")) overrides.set(kind, id, MaterialOverrides.Choice.disabledChoice());
            else if (!action.equals("status")) overrides.set(kind, id,
                    MaterialOverrides.Choice.materialChoice(MaterialType.valueOf(action)));
            if (!action.equals("status")) GeneratedPackManager.updateAndReload();
            var choice = overrides.get(kind, id);
            String description = choice == null ? "automatic" : choice.disabled() ? "disabled"
                    : choice.material().name().toLowerCase(java.util.Locale.ROOT);
            source.sendSuccess(() -> Component.literal("Integrate PBR " + kind.name().toLowerCase(java.util.Locale.ROOT)
                    + " " + id + ": " + description
                    + (action.equals("status") ? "" : ". Updating resource pack...")), false);
            return 1;
        } catch (IOException error) {
            source.sendFailure(Component.literal("Could not save Integrate PBR choice: " + error.getMessage()));
            return 0;
        }
    }
}
