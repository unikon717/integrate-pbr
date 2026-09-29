package dev.integratepbr;

import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.item.ItemStack;

import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/** Reads registered item defaults; recipes are not needed for this evidence. */
final class WeaponSignals {
    private WeaponSignals() {}

    static boolean durableAttacker(Set<ModelTextureIndex.Owner> owners) {
        for (ModelTextureIndex.Owner owner : owners) {
            if (owner.kind() != MaterialOverrides.Kind.ITEM) continue;
            ResourceLocation id = owner.id();
            var item = BuiltInRegistries.ITEM.get(id);
            if (item == null) continue;
            ItemStack stack = item.getDefaultInstance();
            if (stack.getMaxDamage() <= 0) continue;
            AtomicBoolean attack = new AtomicBoolean();
            stack.forEachModifier(EquipmentSlot.MAINHAND, (attribute, modifier) -> {
                if (attribute.equals(Attributes.ATTACK_DAMAGE) && modifier.amount() > 0)
                    attack.set(true);
            });
            if (attack.get()) return true;
        }
        return false;
    }
}
