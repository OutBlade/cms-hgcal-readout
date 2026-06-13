-- CRC-8/CCITT pipeline checker for ECON-D frames
-- Asserts frame_err one clock after the final payload byte if the
-- received CRC does not match the locally computed value.
--
-- Polynomial: x^8 + x^2 + x + 1  (0x07)
-- Initial value: 0x00, no input/output reflection.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity econ_frame_check is
    port (
        clk       : in  std_logic;
        rst_n     : in  std_logic;

        -- Byte-serial input from ECON-D capture buffer
        byte_in   : in  std_logic_vector(7 downto 0);
        byte_valid: in  std_logic;
        -- Pulse high for one cycle on the last payload byte (before CRC byte)
        frame_end : in  std_logic;
        -- Received CRC byte (presented same cycle as frame_end)
        crc_in    : in  std_logic_vector(7 downto 0);

        frame_ok  : out std_logic;
        frame_err : out std_logic
    );
end entity econ_frame_check;

architecture rtl of econ_frame_check is

    -- CRC-8/CCITT lookup table (computed from polynomial 0x07)
    type t_crc_table is array(0 to 255) of std_logic_vector(7 downto 0);

    -- Synthesisable table initialisation (first 16 entries shown, tool expands)
    function init_crc_table return t_crc_table is
        variable tbl : t_crc_table;
        variable crc : unsigned(7 downto 0);
        variable b   : unsigned(7 downto 0);
    begin
        for i in 0 to 255 loop
            crc := to_unsigned(i, 8);
            for j in 0 to 7 loop
                if crc(7) = '1' then
                    crc := (crc(6 downto 0) & '0') xor x"07";
                else
                    crc := crc(6 downto 0) & '0';
                end if;
            end loop;
            tbl(i) := std_logic_vector(crc);
        end loop;
        return tbl;
    end function;

    constant CRC_TABLE : t_crc_table := init_crc_table;

    signal crc_reg    : std_logic_vector(7 downto 0) := (others => '0');
    signal idx        : integer range 0 to 255;

begin

    idx <= to_integer(unsigned(crc_reg xor byte_in));

    p_crc : process(clk)
    begin
        if rising_edge(clk) then
            frame_ok  <= '0';
            frame_err <= '0';

            if rst_n = '0' then
                crc_reg <= (others => '0');
            elsif byte_valid = '1' then
                if frame_end = '1' then
                    -- Update CRC with last data byte, then compare
                    declare
                        final_crc : std_logic_vector(7 downto 0);
                    begin
                        final_crc := CRC_TABLE(idx);
                        if final_crc = crc_in then
                            frame_ok  <= '1';
                        else
                            frame_err <= '1';
                        end if;
                        crc_reg <= (others => '0');  -- reset for next frame
                    end;
                else
                    crc_reg <= CRC_TABLE(idx);
                end if;
            end if;
        end if;
    end process p_crc;

end architecture rtl;
