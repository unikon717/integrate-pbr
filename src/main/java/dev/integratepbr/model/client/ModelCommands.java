package dev.integratepbr.model.client;
import dev.integratepbr.IntegratePbr;
import dev.integratepbr.model.discovery.ResourceSnapshot;
import dev.integratepbr.model.discovery.RuntimeModelObservation;
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
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import java.io.IOException;

@EventBusSubscriber(modid = IntegratePbr.MOD_ID, value = Dist.CLIENT)
public final class ModelCommands {
    private ModelCommands() {}
    @SubscribeEvent
    public static void register(RegisterClientCommandsEvent event) {
        var root = Commands.literal("integratepbr-model");
        root.then(target("held", ResourceSnapshot.Kind.ITEM));
        root.then(target("block", ResourceSnapshot.Kind.BLOCK));
        event.getDispatcher().register(root);
    }
    private static LiteralArgumentBuilder<CommandSourceStack> target(String name, ResourceSnapshot.Kind kind) {
        var target = Commands.literal(name);
        target.then(Commands.literal("snapshot").executes(ctx -> change(ctx.getSource(), kind, "snapshot")));
        target.then(Commands.literal("runtime-snapshot").executes(ctx -> change(ctx.getSource(), kind, "runtime-snapshot")));
        return target;
    }
    private static int change(CommandSourceStack source, ResourceSnapshot.Kind kind, String action) {
        Minecraft minecraft = Minecraft.getInstance();
        if (action.equals("runtime-snapshot") && !minecraft.isSameThread()) {
            source.sendFailure(Component.literal("Runtime query requires client thread."));return 0;
        }
        if (minecraft.player == null || minecraft.level == null) return 0;
        ResourceLocation id;
        if (kind == ResourceSnapshot.Kind.ITEM) {
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
            if (action.equals("snapshot") || action.equals("runtime-snapshot")) {
                var selected = new ResourceSnapshot.Owner(kind,id);
                java.util.List<ResourceSnapshot.Owner> owners = new java.util.ArrayList<>();
                owners.add(selected);
                BuiltInRegistries.ITEM.keySet().stream().sorted(java.util.Comparator.comparing(Object::toString)).map(key->new ResourceSnapshot.Owner(ResourceSnapshot.Kind.ITEM,key)).filter(owner->!owner.equals(selected)).forEach(owners::add);
                BuiltInRegistries.BLOCK.keySet().stream().sorted(java.util.Comparator.comparing(Object::toString)).map(key->new ResourceSnapshot.Owner(ResourceSnapshot.Kind.BLOCK,key)).filter(owner->!owner.equals(selected)).forEach(owners::add);
                var capture = ResourceSnapshot.capture(selected,owners,ResourceSnapshot.access(minecraft.getResourceManager()),ResourceSnapshot.Limits.defaults());
                if(action.equals("runtime-snapshot")) {
                    capture=kind==ResourceSnapshot.Kind.ITEM?RuntimeModelObservation.withHeldAtlasObservation(minecraft,capture):RuntimeModelObservation.withBlockAtlasObservation(minecraft,((BlockHitResult)minecraft.hitResult).getBlockPos(),capture);
                }
                var destination = FMLPaths.GAMEDIR.get().resolve("integratepbr-dev/snapshots/"+java.util.UUID.randomUUID());
                ResourceSnapshot.export(capture,destination);
                int textureCount=capture.textureCount();
                source.sendSuccess(()->Component.literal("Development snapshot "+kind+" "+id+": "+destination+" ("+textureCount+" textures). Renderer/UV unknown; shared discovery is JSON-candidate scope only."),false);
                return 1;
            }
            return 0;
        } catch (IOException error) {
            source.sendFailure(Component.literal("Could not save development snapshot: " + error.getMessage()));
            return 0;
        }
    }
}
